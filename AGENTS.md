# 项目会话指南

## 先读什么

1. `README.md`：项目入口和最常用命令。
2. `docs/ARCHITECTURE.md`：组件、端口、数据流和代码地图。
3. 涉及上车或服务时读 `docs/DEPLOYMENT.md`。
4. 涉及视觉抓取或机械臂时读 `docs/SNACK_BUTLER.md`。
5. 涉及自主移动、探索或返航时读 `docs/AUTONOMOUS_EXPLORATION.md`。
6. 涉及单独供电、辅助板常亮或 USB 反向供电时读 `docs/POWER_AND_USB.md`。

## 项目事实

- 前端位于 `studio-vue/`，技术栈是 Vue 3 + Vite + Ant Design Vue；没有 vue-router，页面由 `App.vue` 的 hash 菜单切换。
- 机器人端位于 `agents/`，是直接复制到 `/home/ubuntu/` 并由 systemd 运行的独立脚本，不是 colcon 包。
- 默认机器人 IP 为 `192.168.3.63`。生产网页端口 `8000`，rosbridge `9090`，web_video_server `8080`，WebRTC `8091`，自然语言 agent `8092`。
- 正式部署入口是 `agents/deploy_snack.sh`；它会构建 `studio-vue/dist`，不要手工编辑 `dist`。
- `deploy_snack.sh` 会安装/更新 `webctl`、`snack-butler`、`llm-agent`，但只会重启已存在的 `jetson-agent` 和 `webrtc-agent`。全新机器人请按部署文档安装这两个服务。
- 真机 ROS 环境来自 `/home/ubuntu/.zshrc`；`snack-butler` 的 systemd 启动命令必须通过 zsh source 它。
- 自主探索由 `explorer_agent.py` 调度 Frontier 目标，避障仍依赖机器人已有 Nav2；它不会自行用 `/cmd_vel` 取代 Nav2。
- 网页手动速度和 Nav2 速度必须经过 `nav_safety_guard.py`；不得恢复 `/cmd_vel` 直发。真机移动前运行 `agents/test_nav_safety.py` 并确认驱动锁默认关闭。

## 修改约束

- 保留用户已有的未提交修改；先看 `git status --short`，不要清理截图、调试脚本或标定改动。
- Git 只维护 `main` 分支。每次完成一项功能修改并通过相应验证后，必须立即创建一次 Git 提交并直接推送到 GitHub `origin/main`；提交信息应准确描述本次功能或修复，不要把已验证的功能长期留在未提交状态。
- 每次完成代码修改并通过相应验证后，直接运行 `agents/deploy_snack.sh` 部署到小车；除非用户当次明确要求不要部署。机器人确认在线时可设置 `NO_WAIT=1`，部署结果和服务状态需要在交付中说明。
- 不要把 API key、机器人密码或 `snack_butler_config.json` 提交进仓库。
- 机械臂默认配置、相机外参、`table_z`、`tool_len` 都是安全关键参数。更改后至少运行运动学/视觉测试；真机先“空跑”，不要直接执行抓取。
- 前端对机器人地址的统一来源是 `studio-vue/src/composables/useRos.js`。新增页面通常还要在 `studio-vue/src/App.vue` 注册菜单项。

## 最小验证

```bash
npm --prefix studio-vue run build
python3 agents/test_kinematics.py
python3 agents/test_vision.py
python3 agents/test_nav_safety.py
python3 agents/test_webctl_bridge.py
```
