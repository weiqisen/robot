# 自主避障探索与返航

## 能力边界

“自主探索”菜单实现以下闭环：

1. 开始时保持底盘锁定，命令机械臂回“收臂位”；确认到位后记录 `map -> base_link` 位姿为原点。
2. 从 `/map` 中寻找“已知自由区与未知区交界”的 Frontier，并聚类选点。
3. 通过 Nav2 `/navigate_to_pose` 前往目标；路径规划、动态避障和恢复行为由 Nav2 负责。
4. 到达后重新读取地图并选择下一处；不可达或超时的目标会加入临时黑名单。
5. 没有 Frontier、达到最长时间或电压过低时，向 Nav2 下发原点目标。

核心逻辑运行在机器人端 `explorer-agent.service`，关掉网页不会终止任务。

返航指回到任务开始位置附近，不包含充电桩识别、精确泊入或自动充电。若定位漂移，返航点也会随地图坐标产生误差。

## 必要条件

- `/map` 持续提供 `nav_msgs/OccupancyGrid`；探索新环境时通常来自 SLAM。
- TF 中能查询 `map -> base_link`。查询失败时会退回 `/odom` 位姿，但只有 map/odom 近似一致时才可靠。
- Nav2 的 `navigate_to_pose` action 已启动。
- 激光雷达、全局代价地图、局部代价地图和控制器工作正常。
- `nav-safety.service` 在线且默认处于锁定状态。
- 地图中的自由区值为 `0`、未知区为 `-1`、障碍为正值，符合 ROS OccupancyGrid 常规约定。

如果只有 `/map` 和 `/odom`，但没有 Nav2，本功能不会自己直接发布 `/cmd_vel` 绕障；页面会显示 Nav2 未就绪并拒绝开始。

仓库通过 `exploration-nav.service` 常驻启动在线 SLAM Toolbox 和 Nav2。基础驱动仍由厂商 `start_app_node.service` 提供，避免重复启动雷达、相机和底盘节点。

## 操作

1. 打开“导航建图”，确认机器人位姿、激光点、地图和橙/红代价层正常。
2. 打开“自主探索”，检查“地图”和“Nav2”均为已就绪。
3. 设置最长时间、单目标超时和最小边界簇。首次建议 5 分钟、60–90 秒、8 格。
4. 清理台阶、透明/低矮障碍、线缆等雷达可能看不到的危险物，准备物理急停。
5. 点击“开始探索”；页面会显示原点、当前目标、到达与跳过数量。
6. “暂停”会取消当前 Nav2 目标并保留任务；“立即返航”结束探索并回原点；“停止且不返航”停在当前位置。

## ROS 接口

命令发布到 `/explorer/cmd`，类型 `std_msgs/String`，内容是 JSON：

```jsonc
{"action":"start","max_minutes":15,"goal_timeout":90,"min_frontier_cells":8}
{"action":"pause"}
{"action":"resume"}
{"action":"home"}
{"action":"stop"}
```

状态发布到 `/explorer/state`，包含 `mode`、`step`、`home`、`target`、`visited`、`blacklisted`、`map_ready`、`nav_ready`、`battery_v` 和当前配置。

### 服务重启后的探索恢复

探索运行期间会把原点、已访问区域、临时黑名单、最后目标和安全位姿检查点原子写入
`~/explorer_session.json`。`explorer-agent` 重启后先检查 `map -> odom` 连续性；通过后仍会保持
底盘锁定并显示“恢复待确认”。此时只能在网页选择“继续探索”（重新选择 Frontier）或“立即返航”，
不会因服务重启自动开车。坐标不连续时旧任务与原点都会作废。

## 安全说明

- “避障”能力取决于 Nav2 和传感器配置。本 agent 不会绕过代价地图直接驱动车轮。
- Nav2 输出 `/nav_cmd_vel`、网页手动输出 `/manual_cmd_vel`，二者必须经过 `nav_safety_guard.py` 才会转发到 `/controller/cmd_vel`。
- 当前真机 `lidar_frame` 相对 `base_link` 绕 Z 轴旋转 180°；安全闸门已按该静态 TF 校正方向，车头近障使用雷达 ±180° 扇区，不得再按 scan 0° 判断车头。
- 安全闸门监视遗留 `/cmd_vel`；发现非零指令会立即锁定、补发零速度，并阻止探索开始。这只是竞态兜底：如果厂商底盘节点也直接订阅 `/cmd_vel`，第一条旁路消息仍可能到达底盘。首次通电调试前必须用 `ros2 topic info /cmd_vel -v` 核实并移除该直达订阅，不能把浏览器急停当成硬件安全回路。
- 安全闸门限制速度为前后 0.12m/s、横移 0.08m/s、旋转 0.45rad/s；运动方向 0.72m 内逐渐减速、0.38m 内停止，车身 0.30m 内禁止原地旋转。
- 近障硬急停连续 3 秒时，探索 agent 会取消并拉黑当前 Frontier，改选其他目标，避免持续对着障碍输出导航意图。
- 探索与返航移动前必须确认机械臂在“收臂位”；“观察位”是 eye-in-hand 视觉姿态，臂展开且重心较高，不作为移动姿态。
- 地图点选导航默认锁定；自主探索跳过小于 0.45m 的无效近目标，单个 Frontier 目标限制在 2m 内。手动驾驶和 Nav2 是互斥控制源，切换必须重新解锁。
- 代价地图按 0.20m 机器人半径和 0.35m 膨胀半径规划，不再使用厂商 0.05m 默认半径。
- 低电压阈值默认 9.7V；触发后尝试返航，但电量过低时不能保证有足够续航完成。
- 开始探索要求电池电压至少 10.5V；没有电池遥测时拒绝启动。
- 楼梯、悬崖、玻璃、镜面、低于扫描平面的物体可能无法被二维雷达识别。没有悬崖传感器时不要在楼梯附近无人值守运行。
- 浏览器急停和网络通信不是硬件安全回路，首次真机测试必须有人在旁并能断电。

## 排障

```bash
systemctl status explorer-agent --no-pager
journalctl -u exploration-nav -n 100 --no-pager
journalctl -u nav-safety -n 100 --no-pager
journalctl -u lidar-watchdog -n 100 --no-pager
journalctl -u explorer-agent -n 100 --no-pager
ros2 topic echo /explorer/state
ros2 action list | grep navigate_to_pose
ros2 run tf2_ros tf2_echo map base_link
```

| 现象 | 常见原因 |
|---|---|
| 页面一直“节点未连接” | `explorer-agent` 未部署/未启动，或 rosbridge 没转发状态 topic |
| 地图未就绪 | SLAM/地图服务未启动，或 `/map` 名称不同 |
| Nav2 未就绪 | BT navigator 未启动，或 action 名不是 `/navigate_to_pose` |
| 一开始就返航 | 地图没有未知区、Frontier 太小，或目标附近障碍太多；降低最小边界簇前先确认地图 |
| 多个目标连续跳过 | 全局规划失败、目标落在未知区边缘、代价地图膨胀过大或机器人定位错误 |
| 回不到精确起点 | SLAM/AMCL 漂移、map/odom 不一致，或原点附近后来被占用 |
| 雷达在转但页面离线 | USB 曾断连、驱动仍握旧串口；`lidar-watchdog` 会在确认 `/dev/lidar` 存在后尝试恢复 |
