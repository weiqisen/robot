# JetRover Robot Console

这是一个运行在 JetRover/Jetson 上的机器人控制台：浏览器端用 Vue 展示遥测、ROS 状态、相机、导航、机械臂和数字孪生；机器人端的 Python agents 负责采集 Jetson 状态、视频转发、视觉抓取和自然语言控制。

## 快速入口

- [Web 项目完整入门指南](WEB_PROJECT_GUIDE.md)：从零理解代码、架构、页面、ROS 数据流、业务逻辑、安全设计和开发流程。
- [部署与运维](docs/DEPLOYMENT.md)：本地启动、上车部署、首次安装、服务检查和回滚思路。
- [运维手册](docs/OPERATIONS_RUNBOOK.md)：相机、日志、服务、探索与部署的日常排障边界。
- [架构与代码地图](docs/ARCHITECTURE.md)：组件关系、端口、数据流，以及需求应从哪里改。
- [视觉抓取](docs/SNACK_BUTLER.md)：视觉定位、机械臂标定、抓取参数和专项排障。
- [自主探索](docs/AUTONOMOUS_EXPLORATION.md)：Frontier 探索、Nav2 避障、返航与安全边界。
- [高可用路线](docs/HIGH_AVAILABILITY_ROADMAP.md)：自主探索与视觉抓取的故障隔离、恢复和续跑规划。
- [Mac 本地模拟器](docs/LOCAL_SIMULATOR.md)：小车充电/关机时的网页与任务流程联调。
- [供电与 USB](docs/POWER_AND_USB.md)：Jetson/辅助板电源域、反向供电和正确断电方式。
- [会话须知](AGENTS.md)：给后续 Codex/AI 会话的最短项目上下文。

## 本地预览

本地只启动网页；没有机器人时 ROS、相机和硬件数据会显示离线。

```bash
cd studio-vue
npm ci
npm run dev
```

打开 <http://localhost:5273>。本地开发默认连接 `192.168.3.63`；从机器人 `:8000` 打开时，前端自动使用当前网页的主机名。

## 部署摘要

```bash
# 默认等候 192.168.3.63 上线，然后构建网页、推送 agents 并重启服务
./agents/deploy_snack.sh

# 常用覆盖
ROBOT=192.168.3.99 ROBOT_USER=ubuntu ./agents/deploy_snack.sh
WEB_ONLY=1 NO_WAIT=1 ./agents/deploy_snack.sh
```

部署完成后访问 `http://<机器人IP>:8000`。完整前置条件和首次安装步骤见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 验证

```bash
npm --prefix studio-vue run build
python3 agents/test_kinematics.py
python3 agents/test_vision.py
python3 agents/test_nav_safety.py
python3 agents/test_webctl_bridge.py
```

`test_pipeline.py` 另需 `numpy` 和 `opencv-python-headless`。涉及真机运动前，先阅读 [docs/SNACK_BUTLER.md](docs/SNACK_BUTLER.md) 并使用“空跑”。
