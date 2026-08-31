# 部署与运维

## 部署模型

开发机负责构建 Vue 静态文件，再通过 SSH/SCP 复制到机器人。生产文件位于 `/home/ubuntu/web_control`，Python agents 位于 `/home/ubuntu`，服务由 systemd 常驻。

默认值：

```text
机器人地址  192.168.3.63
SSH 用户    ubuntu
网页地址    http://<机器人IP>:8000
```

## 前置条件

开发机需要 Node.js/npm、`ssh`、`scp`、`tar`、`nc`。使用密码自动登录时还需要 `sshpass`；更推荐配置 SSH key。

项目根目录可放置本地 `.robot.env`，部署脚本会自动读取。该文件匹配 `.gitignore` 的 `*.env`，不会提交到 Git：

```bash
ROBOT="${ROBOT:-192.168.3.63}"
ROBOT_USER="${ROBOT_USER:-ubuntu}"
ROBOT_PASS="${ROBOT_PASS:-你的密码}"
```

外部传入的同名环境变量仍然优先，方便临时部署另一台机器人。

机器人应已具备厂商 ROS 2 环境，以及 rosbridge `:9090`、web_video_server `:8080`。完整功能还可能需要：

- `websocket-client`：`jetson_agent.py` 和 `llm_agent.py`。
- `numpy`、OpenCV、`rclpy` 及厂商消息包：`snack_butler.py`。
- `aiohttp`、`aiortc`、`av`、OpenCV：`webrtc_agent.py`。
- `anthropic`：`llm_agent.py`。

这些 ROS/硬件依赖与 JetPack、厂商镜像绑定，不建议在开发机的普通 Python 环境中模拟安装。

## 日常部署

在仓库根目录执行：

```bash
./agents/deploy_snack.sh
```

脚本默认持续等待 SSH 端口上线，适合机器人断电后“蹲守”部署。可用环境变量：

| 变量 | 默认 | 作用 |
|---|---|---|
| `ROBOT` | `192.168.3.63` | 机器人 IP/主机名 |
| `ROBOT_USER` | `ubuntu` | SSH 用户 |
| `ROBOT_PASS` | 空 | 配合本机 `sshpass` 免交互登录；不要写入仓库 |
| `NO_WAIT` | 空 | 非空时跳过在线等待 |
| `WEB_ONLY` | 空 | 非空时只部署网页和 `webctl` |

示例：

```bash
ROBOT=192.168.3.99 NO_WAIT=1 ./agents/deploy_snack.sh
WEB_ONLY=1 ./agents/deploy_snack.sh
```

脚本会：

1. 在 `studio-vue/` 运行 `npm run build`。
2. 打包 `dist/`，清理机器人旧的 hash assets 后解压到 `~/web_control`。
3. 更新 `webctl_server.py` 并安装/重启 `webctl.service`。
4. 非 `WEB_ONLY` 时复制 agents，并保留已有 `~/snack_butler_config.json`。
5. 重启已经安装的 `jetson-agent`、`webrtc-agent`。
6. 安装/重启 `snack-butler`、`lidar-watchdog`、`nav-safety`、`exploration-nav` 和 `explorer-agent`；存在 `~/.llm_agent.env` 时启用 `llm-agent.service`。

注意：这是部署脚本，不是完整的机器人镜像初始化器。它不会安装 rosbridge、web_video_server、x11vnc，也不会首次创建 `jetson-agent.service` 和 `webrtc-agent.service`。

## 全新机器的一次性补充

先执行一次日常部署，把脚本复制到机器人。然后按实际 Python 路径和依赖安装下面两个服务：

```ini
# /etc/systemd/system/jetson-agent.service
[Unit]
Description=JetRover Jetson telemetry agent
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu
ExecStart=/usr/bin/python3 /home/ubuntu/jetson_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/webrtc-agent.service
[Unit]
Description=JetRover WebRTC video agent
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu
ExecStart=/usr/bin/python3 /home/ubuntu/webrtc_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jetson-agent webrtc-agent
```

若 `webrtc-agent` 使用虚拟环境，请把 `ExecStart` 改为该环境的 Python。安装前先用 `python3 /home/ubuntu/webrtc_agent.py` 暂时运行，确认依赖无误。

### 自然语言服务

机器人端创建仅自己可读的环境文件：

```bash
printf 'ANTHROPIC_API_KEY=你的密钥\n' > ~/.llm_agent.env
chmod 600 ~/.llm_agent.env
sudo systemctl enable --now llm-agent
```

还可在该文件设置 `ROSBRIDGE_URL`、`LLM_AGENT_PORT`、`LLM_MODEL`、`LLM_EFFORT`。不要把环境文件或密钥提交到 Git。

## 部署后检查

```bash
curl -I http://<机器人IP>:8000/
curl http://<机器人IP>:8091/health
curl http://<机器人IP>:8092/health

ssh ubuntu@<机器人IP> 'systemctl --no-pager --full status webctl snack-butler lidar-watchdog nav-safety exploration-nav explorer-agent jetson-agent webrtc-agent llm-agent'
```

`llm-agent` 未配置时不运行是正常的。还应在浏览器检查：顶部 ROS 状态在线、Jetson 页面有遥测、相机画面可用、运行日志有数据。

常用日志：

```bash
sudo journalctl -u webctl -n 100 --no-pager
sudo journalctl -u snack-butler -n 100 --no-pager
sudo journalctl -u explorer-agent -n 100 --no-pager
sudo journalctl -u exploration-nav -n 100 --no-pager
sudo journalctl -u nav-safety -n 100 --no-pager
sudo journalctl -u lidar-watchdog -n 100 --no-pager
sudo journalctl -u jetson-agent -n 100 --no-pager
sudo journalctl -u webrtc-agent -n 100 --no-pager
sudo journalctl -u llm-agent -n 100 --no-pager
```

## 常见问题

| 现象 | 检查 |
|---|---|
| 部署后页面仍是旧版 | 确认访问 `:8000`，检查 `webctl` 是否重启及 `index.html` 修改时间；不要改 `dist` |
| 页面打开但全部 ROS 数据离线 | 检查 `:9090`、rosbridge/rosapi，以及浏览器是否能直达机器人端口 |
| Jetson/服务/日志页面空白 | `jetson-agent.service` 可能未安装、缺 `websocket-client` 或连不上本机 rosbridge |
| 相机只有 MJPEG 没有 WebRTC | 检查 `:8091/health` 和 aiortc/av/OpenCV 依赖；MJPEG 回退仍可用 |
| `snack-butler` 报 ROS 环境错误 | systemd 必须用 zsh source `/home/ubuntu/.zshrc`，以加载厂商 `need_compile/HOST/MASTER` 配置 |
| `llm-agent` 不启动 | 检查 `~/.llm_agent.env` 权限、API key、外网和 Python 依赖 |
| 机器人反复掉线 | 先检查电池；3S 电池接近 9V 时可能欠压重启 |

## 回滚

仓库没有制品仓库或自动回滚。安全做法是在部署前保留上一份 Git commit/tag；需要回滚时切到已知版本并重新运行部署脚本。`snack_butler_config.json` 不会被脚本覆盖，因此代码回滚与标定配置回滚是两件事；若需要回退标定，应事先单独备份机器人上的该文件。
