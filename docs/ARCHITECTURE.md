# 架构与代码地图

本文描述当前已部署的 Robot Dashboard：谁负责什么、数据如何走、控制如何被约束，以及改一项功能通常应从哪里开始。

## 设计目标

- **一个入口**：浏览器在 `:8000` 查看机器人、执行受限控制和学习 ROS。
- **真实状态优先**：仪表、数字孪生和服务状态来自机器人实时反馈，而不是前端预测。
- **分层恢复**：视频、抓取、导航和基础 ROS 可分别恢复，避免为一个页面异常重启整车。
- **安全默认值**：底盘速度必须经过安全闸门；抓取先做可达性判断；学习页不开放执行器话题。

## 全局视图

```text
浏览器（Vue 3 / Vite）
  ├─ 工作台：态势、相机、数字孪生、动作组、抓取、导航、ROS 学习、运维
  ├─ HTTP API ──────────────────────────────> webctl :8000
  ├─ ROS WebSocket ─────────────────────────> rosbridge :9090
  ├─ 低延迟视频 ────────────────────────────> WebRTC agent :8091
  └─ 兼容视频 / 调试 ────────────────────────> MJPEG :8080 / 视觉流 :8082

Jetson / ROS 2
  ├─ start_app_node：相机、雷达、底盘、IMU、机械臂与基础 ROS bringup
  ├─ snack-butler：视觉检测、深度定位、IK、抓取状态和动作组桥接
  ├─ exploration-nav + explorer-agent：SLAM/Nav2 与 Frontier 任务调度
  ├─ nav-safety：所有底盘速度的安全闸门
  ├─ jetson-agent：遥测、日志、服务状态和资源诊断
  ├─ webrtc-agent / vision-video / vision-stream-guard：视频转发和恢复
  └─ lidar-watchdog / llm-agent：雷达恢复与自然语言入口
```

## 服务层与职责

| 层 | 组件 | 职责 | 可否独立恢复 |
| --- | --- | --- | --- |
| 基础硬件 | `start_app_node` | RGB/深度相机、雷达、底盘、里程计、IMU、舵机、rosbridge 与 MJPEG 基础 bringup | 影响面最大，只在上游硬件/ROS 明确异常时重启 |
| Web 与运维 | `webctl`、`jetson-agent` | 静态网页/API、系统遥测、日志流、服务和资源诊断 | 可以独立重启，不驱动硬件 |
| 视觉抓取 | `snack-butler` | 检测、深度坐标、可达性、抓取编排、动作组接口 | 可以独立重启；不应修改标定文件 |
| 视频 | `webrtc-agent`、`vision-video`、`vision-stream-guard` | WebRTC、MJPEG 兼容流和无帧恢复 | 先恢复此层，再升级到基础 bringup |
| 导航 | `exploration-nav`、`explorer-agent`、`nav-safety` | Nav2/SLAM、Frontier 探索、返航、速度守门 | 可进入待机释放资源；`nav-safety` 不应随意停止 |
| 设备守护 | `lidar-watchdog` | 识别雷达断连并按规则恢复 | 雷达可物理关闭，离线并不总是故障 |

## 网络端口与协议

| 端口 | 服务 | 用途 |
| --- | --- | --- |
| `8000` | `webctl` | 工作台静态网页、受限运维 API、运行日志和诊断数据 |
| `9090` | rosbridge | 浏览器订阅 ROS 话题、调用允许的服务 |
| `8080` | `web_video_server` | ROS 图像的 MJPEG/兼容调试路径 |
| `8082` | `vision-video` | 视觉标注图的轻量 MJPEG 路径 |
| `8091` | `webrtc-agent` | 优先使用的低延迟视频信令与媒体通道 |
| `8092` | `llm-agent` | 自然语言指令入口 |

端口在线只说明进程可连接，不等于上游确实有帧或有 ROS 消息。工作台会同时显示传输方式、帧率和服务状态，排障时应三者一起看。

## 关键数据流

### 1. 遥测、日志与服务状态

`jetson-agent` 采集 CPU、GPU、内存、温度、磁盘、网络和 systemd 服务状态，经 ROS/HTTP 提供给页面。运维面板的服务卡片是“受管对象”的投影；它不是 Kubernetes，也不会任意执行前端传入的 shell 命令。

### 2. 相机与视觉抓取

```text
相机 RGB/深度 → start_app_node ROS 话题
              ├→ snack-butler：检测 → 深度反投影 → 坐标变换 → IK/评分
              │                    └→ 标注图、目标、抓取决策、关节状态
              └→ 视频转发：WebRTC 优先；MJPEG 作为降级与诊断
```

抓取确认前，前端只展示候选与诊断。服务端再次检查目标新鲜度、深度、供电、驱动映射与 IK；任何一项失败都会拒绝执行。

### 3. 底盘与导航

```text
手动网页速度 / Nav2 输出 / 探索任务
                → nav_safety_guard
                → 驱动允许的速度话题
                → 底盘控制器
```

安全锁默认关闭、超时会停、无效来源会被拒绝。探索 agent 只选择 Frontier 目标并交给 Nav2，不直接绕过安全闸门发布到底盘。

### 4. 机械臂与数字孪生

机械臂动作组或抓取编排发送到已有舵机映射；真实关节反馈回到 ROS。前端数字孪生只读取该反馈并在浏览器内插值渲染，不能反向控制机械臂。这样既能平滑展示，又避免“预测目标位姿”在真实机械臂尚未动作前形成幻影。

## 状态与配置归属

| 内容 | 归属 | 说明 |
| --- | --- | --- |
| 菜单、视图布局、临时选择 | 浏览器 | 刷新后可重建，不作为机器人真实状态 |
| 服务状态、资源、日志 | Jetson/systemd | 由 `jetson-agent` 与 `webctl` 读取 |
| 相机帧、目标、关节状态 | ROS | 应以时间戳和新鲜度判断有效性 |
| 抓取标定与安全参数 | `/home/ubuntu/snack_butler_config.json` | 机器专属，部署不会覆盖，也不应提交仓库 |
| 动作组 | 机器人已有动作组存储/ROS 接口 | 页面只是编辑与执行入口 |

## 代码地图

| 想改什么 | 主要位置 |
| --- | --- |
| 菜单与页面挂载 | `robot-dashboard-front/src/App.vue` |
| ROS 连接、地址与订阅公共逻辑 | `robot-dashboard-front/src/composables/useRos.js` |
| 态势中心和数字孪生 | `robot-dashboard-front/src/views/` 中对应工作台视图与组件 |
| 运维面板/API 展示 | `robot-dashboard-front/src/views/Logs.vue`、`agents/webctl_server.py` |
| 视觉抓取与动作组 | `agents/snack_butler.py`、`agents/snack_detector.py`、`agents/arm_kinematics.py` |
| 视频 | `agents/webrtc_agent.py`、`agents/vision_stream_server.py`、`agents/vision_stream_guard.py` |
| 自主探索与安全速度 | `agents/explorer_agent.py`、`agents/nav_safety_guard.py` |
| 一键部署 | `agents/deploy_snack.sh` |

## 修改边界

- 新增网页功能应优先复用 `useRos.js`，不要在多个页面硬编码机器人地址。
- 新增底盘控制必须进入 `nav_safety_guard.py`；禁止恢复 `/cmd_vel` 直发。
- 不要手改 `robot-dashboard-front/dist`；它是构建产物，部署脚本会重新生成。
- 调整相机外参、`table_z`、`tool_len` 或默认机械臂姿态前，必须运行运动学/视觉测试并先空跑。
- 服务恢复按“视频 → 视觉节点 → 基础 bringup”的影响范围逐级升级，详见[运维手册](OPERATIONS_RUNBOOK.md)。
