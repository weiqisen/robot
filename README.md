# JetRover Robot Dashboard

JetRover Robot Dashboard 是一套面向 Jetson 轮式机械臂机器人的开源工作台。它把 ROS 话题、相机、导航、视觉抓取、数字孪生和设备运维收拢到一个浏览器界面，让第一次接触 ROS 的操作者也能安全地观察、学习与操作机器人。

> 这是控制台，不是对硬件安全机制的替代品。第一次运动、改动机械臂标定或底盘速度前，请先阅读专项文档并完成空跑检查。

## 你可以用它做什么

| 能力 | 在工作台中完成的事 |
| --- | --- |
| 实时态势 | 查看相机、雷达、底盘、电源、CPU/GPU、ROS 节点和服务状态 |
| 视觉引导抓取 | 识别目标、校验坐标、执行安全抓取，并追溯决策过程 |
| 自主移动 | 设定探索/返航任务；速度始终经过安全闸门 |
| 数字孪生 | 用真实关节反馈平滑驱动机械臂模型，便于在执行时观察动作 |
| ROS 学习 | 浏览话题、订阅实时消息，并只在安全学习话题上演练发消息 |
| 运维 | 在“运维面板”观察服务、日志、资源与视频链路，执行受限的启停和恢复 |

## 五分钟开始

1. 让机器人接入局域网并确认浏览器可访问 `http://<机器人IP>:8000`。
2. 打开“态势中心”，确认通信链路在线、电源正常、驱动仍处于锁定状态。
3. 先在“项目文档 → 快速开始”完成一次安全检查，再按任务进入“视觉引导抓取”或“自主导航”。
4. 需要排障时从“运维面板”开始：先看事件日志和服务卡片，再按文档处理，不要直接杀 ROS 进程。

默认机器人地址为 `192.168.3.63`；从机器人自身的网页打开时，前端会自动使用当前主机名。

## 文档导航

### 使用者

- [快速开始](docs/GETTING_STARTED.md)：开机后的首个安全任务、各页面应该怎么用。
- [视觉引导抓取](docs/SNACK_BUTLER.md)：识别、标定、可达性、抓取确认与专项排障。
- [自主探索](docs/AUTONOMOUS_EXPLORATION.md)：探索、返航、导航待机和移动安全边界。
- [供电与 USB](docs/POWER_AND_USB.md)：供电域、反向供电和正确断电方式。

### 开发者

- [架构与代码地图](docs/ARCHITECTURE.md)：服务分层、端口、数据流、状态归属和安全边界。
- [Web 开发者指南](WEB_PROJECT_GUIDE.md)：Vue 页面、ROS 桥接、接口约定和本地调试。
- [Mac 本地模拟器](docs/LOCAL_SIMULATOR.md)：无真机时联调网页与任务流程。

### 部署与运维

- [部署指南](docs/DEPLOYMENT.md)：环境要求、首次安装、更新、验证与回退。
- [运维手册](docs/OPERATIONS_RUNBOOK.md)：服务/POD 管理、图形桌面、视频恢复和故障决策树。
- [高可用路线](docs/HIGH_AVAILABILITY_ROADMAP.md)：当前恢复策略和后续故障隔离规划。

## 本地开发

```bash
cd robot-dashboard-front
npm ci
npm run dev
```

访问 <http://localhost:5273>。本地只运行前端；ROS、相机和硬件数据取决于机器人是否在线。

## 部署与验证

```bash
# 默认等待目标机器人 SSH 上线，再构建、推送并重启受管服务
./agents/deploy_snack.sh

# 常用覆盖：只更新网页，或指定另一台机器人
WEB_ONLY=1 NO_WAIT=1 ./agents/deploy_snack.sh
ROBOT=192.168.3.99 ROBOT_USER=ubuntu ./agents/deploy_snack.sh

# 提交前的最小验证
npm --prefix robot-dashboard-front run build
python3 agents/test_kinematics.py
python3 agents/test_vision.py
python3 agents/test_nav_safety.py
python3 agents/test_webctl_bridge.py
```

部署脚本会打包网页和项目文档，并更新机器人端 agents；标定参数和本机密钥不应提交到仓库。完整步骤见[部署指南](docs/DEPLOYMENT.md)。

## 贡献约定

- 前端页面在 `robot-dashboard-front/`，没有 vue-router，菜单由 `App.vue` 的 hash 切换。
- 机器人端脚本在 `agents/`，部署后由 systemd 直接运行，并非 colcon 包。
- 新增移动控制必须经过 `nav_safety_guard.py`；不要恢复对 `/cmd_vel` 的直发。
- 机械臂默认姿态、相机外参和抓取高度均为安全关键配置。改动后先运行测试，再真机空跑。
- 提交前保留并更新相关文档，让操作者知道变化带来的行为和风险。
