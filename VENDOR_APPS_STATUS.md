# JetRover 厂商默认应用停用记录

更新时间：2026-09-05

## 当前策略

机器人上的厂商源码和 launch 文件没有删除。`start_app_node.service` 已改为启动项目维护的
`/home/ubuntu/web_bringup.launch.py`，只加载网页工作台需要的基础能力，避免无用演示节点常驻占用
CPU、内存和相机资源。

对应仓库文件：

- `agents/web_bringup.launch.py`
- `agents/deploy_snack.sh`

## 已停止的厂商默认节点

| 节点 | 厂商功能 | 停用原因 |
|---|---|---|
| `/line_following` | 巡线演示 | 网页工作台未使用，持续占用视觉与 CPU |
| `/object_tracking` | 目标追踪演示 | 与当前 YOLO 抓取链路无关，持续占用视觉与 CPU |
| `/ar_app` | AR 标签应用 | 网页工作台未使用 |
| `/hand_gesture` | 手势识别 | 网页工作台未使用，视觉计算开销较高 |
| `/lidar_app` | 厂商雷达玩法/避障演示 | 当前导航使用 Nav2、`nav_safety_guard` 和独立雷达驱动 |
| `/joystick_control` | 实体摇杆控制 | 网页驾驶统一经过 `/manual_cmd_vel -> nav_safety`，避免旧入口旁路 |
| `/init_pose` | 厂商启动姿态应用 | 机械臂初始化与恢复由 `snack_butler` 状态机负责 |

这些节点只是不会随 `start_app_node` 启动，软件包及源文件仍保留在机器人上。

## 仍然保留的核心能力

- 底盘控制器、舵机控制器、机械臂和夹爪
- IMU、里程计、EKF、TF 与 robot state publisher
- 深度相机、激光雷达及雷达过滤
- rosbridge、rosapi、web video server
- `snack-butler` 视觉抓取
- `nav-safety` 导航安全闸门
- Nav2、SLAM 与自主探索
- 网页、WebRTC、自然语言服务和运行监控

## 实施后的真机验证

- 上述 7 个厂商演示/控制节点均未再出现。
- `start_app_node`、`snack-butler`、`lidar-watchdog`、`nav-safety`、
  `exploration-nav`、`explorer-agent`、`vision-video`、`webctl` 均为 `active`。
- 网页相关端口 `8000`、`8080`、`8091`、`8092`、`9090` 均可访问。
- 可用内存由约 304 MB 提升到约 789 MB；视觉、相机和 Nav2 仍是主要负载。

## 如何恢复厂商完整模式

如需重新使用巡线、手势或 AR 等厂商功能，把 `start_app_node.service` 的启动命令恢复为：

```ini
ExecStart=/usr/bin/zsh -c 'source /home/ubuntu/.zshrc; exec ros2 launch bringup bringup.launch.py'
```

然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart start_app_node.service
```

注意：再次运行当前版本的 `agents/deploy_snack.sh` 会重新启用轻量网页模式。恢复完整厂商模式后，
应重新检查 `/cmd_vel` 是否存在绕过 `nav_safety_guard` 的控制入口，并观察 CPU 与内存占用。
