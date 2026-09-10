# 部署指南

本指南用于把仓库更新安全地部署到 JetRover。正式入口只有一个：`agents/deploy_snack.sh`。它会构建网页、连同项目文档一起打包，推送机器人端脚本，并更新/重启受管服务。

## 部署模型

```text
开发机仓库
  └─ agents/deploy_snack.sh
       ├─ npm run build → studio-vue/dist
       ├─ 复制 README 与 docs → dist/project-docs
       ├─ SCP 网页与 agents 到 /home/ubuntu/
       ├─ 更新 webctl / snack-butler / 相关 systemd 单元
       └─ 重启已安装的守护服务，输出服务状态
```

不要直接修改 `studio-vue/dist`：下一次构建会覆盖它。机器人上的标定配置 `/home/ubuntu/snack_butler_config.json` 是机器专属文件，脚本只会在缺失时创建空文件，不会覆盖现有标定。

## 环境要求

### 开发机

- macOS 或 Linux，具备 `bash`、`ssh`、`scp`、`tar` 和 Node.js/npm。
- 能通过 SSH 访问机器人；建议配置 SSH key。需要密码时，通过本地环境变量传给脚本，绝不写入仓库。
- 前端依赖安装完成：`npm --prefix studio-vue ci`。

### 机器人

- Ubuntu + ROS 2 Humble 与厂商 ROS 环境；真实环境变量由 `/home/ubuntu/.zshrc` 提供。
- 默认 IP 是 `192.168.3.63`，网页端口是 `8000`。
- 已具备基础硬件与 ROS bringup 依赖；首次装机还需按本项目 systemd 单元要求安装 `jetson-agent` 与 `webrtc-agent`。
- systemd 可使用 `sudo` 管理项目服务；部署脚本会安装所需单元和雷达 udev 规则。

## 首次部署

1. 确认机器人已开机、接入网络，并能 SSH 登录。
2. 在开发机根目录执行：

```bash
npm --prefix studio-vue ci
./agents/deploy_snack.sh
```

3. 脚本默认会等待 SSH 上线，适合机器人刚开机或电池恢复后部署。
4. 打开 `http://<机器人IP>:8000`，进入“运维面板”确认核心服务与事件日志正常。
5. 第一次让底盘或机械臂动作前，执行下面的验证，并遵循专项文档的空跑步骤。

## 日常更新

```bash
# 机器人已经在线，不再等待
NO_WAIT=1 ./agents/deploy_snack.sh

# 仅更新网页与项目文档；不推 agents、不触碰硬件服务
WEB_ONLY=1 NO_WAIT=1 ./agents/deploy_snack.sh

# 指向临时或另一台测试机器人
ROBOT=192.168.3.99 ROBOT_USER=ubuntu NO_WAIT=1 ./agents/deploy_snack.sh
```

可在本机创建已被 Git 忽略的 `.robot.env` 保存非敏感默认项，例如 `ROBOT`、`ROBOT_USER`。密码、API key、标定文件与 `.llm_agent.env` 不应进入 Git。

## 部署后验证

```bash
npm --prefix studio-vue run build
python3 agents/test_kinematics.py
python3 agents/test_vision.py
python3 agents/test_nav_safety.py
python3 agents/test_webctl_bridge.py
```

真机检查顺序：

1. 网页 `:8000` 可打开，项目文档页能加载最新 Markdown。
2. 运维面板中 `webctl`、`jetson-agent`、`snack-butler`、`start_app_node` 为运行状态。
3. 相机画面有帧率；出现黑屏时先验证 WebRTC/MJPEG 实际是否有帧。
4. 驱动默认保持锁定，且导航/抓取在空场前不执行真实动作。

## 服务与启动模式

### 图形桌面

为节省 Jetson CPU/内存，机器人可在无桌面模式运行。运维面板提供“图形桌面”开关：开启会恢复 graphical target 与显示管理器，关闭会回到 multi-user target。它影响触摸屏/本地图形界面，不影响网页工作台。

等价脚本在机器人 `/home/ubuntu/enable_desktop.sh` 与 `/home/ubuntu/disable_desktop.sh`。桌面状态改变后，等待系统完成切换再判断资源占用。

### 自主导航待机

运维面板的“自主导航待机”会停止探索与在线 SLAM/Nav2 资源，保留相机、抓取、雷达守护和速度安全闸门。需要恢复导航时使用同一开关。部署会重装并启用导航相关服务，因此计划长时间待机时，应在部署完成后再切回待机。

### 基础 ROS bringup

`start_app_node` 是最底层的项目 bringup，托管相机、雷达、底盘、IMU、机械臂与基础 ROS 组件。重启它会短暂中断依赖节点；只应在确认上游话题/硬件已经异常且视频层、视觉节点层恢复无效后执行。

## 回退与失败处理

- **网页显示旧版本**：浏览器强制刷新后再试。`webctl` 会以无缓存方式服务入口和带 hash 的 assets；不要手工修改远端 `assets/`。
- **部署中断**：重新执行同一条部署命令即可。网页包采用整体解压，agent 与 systemd 单元会被重新写入。
- **某个功能异常**：先在运维面板查看服务卡片和事件日志，按[运维手册](OPERATIONS_RUNBOOK.md)的影响范围逐层恢复。
- **要回到上一版本**：在开发机切换到已验证的 Git 提交，再运行部署脚本。不要用远端手工复制旧文件拼凑回退。

## 不应做的事

- 不要用 `kill -9` 或直接删除 systemd 单元处理普通页面故障。
- 不要把 `snack_butler_config.json`、密码、token 或设备专属标定提交进仓库。
- 不要为“让车动起来”绕过 `nav_safety_guard.py`。
- 不要在未空跑验证的情况下修改机械臂几何与抓取参数。
