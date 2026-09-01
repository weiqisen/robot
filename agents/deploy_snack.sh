#!/usr/bin/env bash
# 把视觉抓取部署到 JetRover。机器人常因电量低反复断电，所以默认「蹲守」：
# 一直等到 SSH 通了再推送，不用守着开机。
#
#   ./agents/deploy_snack.sh                  # 蹲守 + 部署代码和网页
#   ROBOT=192.168.3.63 ./agents/deploy_snack.sh
#   NO_WAIT=1 ./agents/deploy_snack.sh        # 机器人已在线，别等
#   WEB_ONLY=1 ./agents/deploy_snack.sh       # 只推网页
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 项目内可选的本机部署配置（*.env 已被 Git 忽略）。外部环境变量优先，
# 文件里也应使用 ${VAR:-default}，避免覆盖临时指定的另一台机器人。
if [ -f "$HERE/.robot.env" ]; then
  # shellcheck disable=SC1091
  source "$HERE/.robot.env"
fi
ROBOT="${ROBOT:-192.168.3.63}"
USER_="${ROBOT_USER:-ubuntu}"
# 一次部署会执行很多 ssh/scp。复用同一条控制连接，避免机器人端在短时间内
# 反复做密码认证后触发限流，造成部署到一半 Permission denied。
SSH_CONTROL="/tmp/jetrover-deploy-%r@%h-%p"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o ControlMaster=auto -o ControlPersist=120 -o ControlPath=$SSH_CONTROL"
# 有 sshpass + ROBOT_PASS 就免交互，否则走 ssh key / 手输密码
if [ -n "${ROBOT_PASS:-}" ] && command -v sshpass >/dev/null; then
  SSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS"; SCP="sshpass -p $ROBOT_PASS scp $SSH_OPTS"
else
  SSH="ssh $SSH_OPTS"; SCP="scp $SSH_OPTS"
fi

if [ -z "${NO_WAIT:-}" ]; then
  echo "== 等机器人 $ROBOT 上线（Ctrl-C 退出）"
  until nc -z -G 3 "$ROBOT" 22 2>/dev/null || nc -z -w 3 "$ROBOT" 22 2>/dev/null; do
    printf '.'; sleep 5
  done
  echo " 上线了"
fi

echo "== 推送网页"
( cd "$HERE/studio-vue" && npm run build >/dev/null )
# macOS 会把 com.apple.* 扩展属性写进 tar，Linux 解包时刷几十行无意义警告。
COPYFILE_DISABLE=1 tar -C "$HERE/studio-vue/dist" -czf /tmp/webctl.tgz .
$SCP /tmp/webctl.tgz "$USER_@$ROBOT:/tmp/"
# 先删旧 assets 再解包：文件名带 hash，不删就会越堆越多
$SSH "$USER_@$ROBOT" 'mkdir -p ~/web_control && rm -rf ~/web_control/assets && tar -C ~/web_control -xzf /tmp/webctl.tgz && rm /tmp/webctl.tgz'

# 静态服务：必须用我们自己那个会发 Cache-Control 的，不能用 python3 -m http.server。
# 后者一个缓存头都不发，浏览器把 index.html 和旧 assets 一起缓存住，
# 新包推上去了刷新还是旧界面，且不报错 —— 排查起来非常费时间。
$SCP "$HERE/agents/webctl_server.py" "$USER_@$ROBOT:~/"
$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/webctl.service >/dev/null <<'EOF'
[Unit]
Description=JetRover Studio
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_
WorkingDirectory=/home/$USER_/web_control
ExecStart=/usr/bin/python3 /home/$USER_/webctl_server.py
Restart=on-failure
RestartSec=4

[Install]
WantedBy=multi-user.target
EOF"
$SSH "$USER_@$ROBOT" 'sudo systemctl daemon-reload && sudo systemctl enable --now webctl && sudo systemctl restart webctl'
echo "== webctl 已重启"
[ -n "${WEB_ONLY:-}" ] && { echo "== 只推网页，完成"; exit 0; }

echo "== 推送 agents"
# jetson_agent / webrtc_agent 的 systemd 单元是早先手工装的，这里只更新脚本本身：
# 网页的 BOM / 服务监控 / 运行日志页全靠 jetson_agent 推 topic，漏推就是一直空转。
$SCP "$HERE"/agents/{snack_butler.py,arm_kinematics.py,vision_geometry.py,snack_detector.py,service_watchdog.py,llm_agent.py,jetson_agent.py,webrtc_agent.py,gpu_bench.py,explorer_agent.py,exploration_bringup.launch.py,run_exploration_nav.sh,run_x11vnc.sh,nav_safety_guard.py,nav_safety_logic.py,lidar_watchdog.py,exploration_nav_safety.yaml} \
     "$USER_@$ROBOT:~/"
# scp 不保证本地脚本的执行位在所有目标环境中保持一致；显式设置，便于 systemd 和人工排障直接执行。
$SSH "$USER_@$ROBOT" 'chmod 755 ~/run_exploration_nav.sh ~/run_x11vnc.sh'
# 配置文件已存在就不覆盖——上面标定出来的参数在里面
$SSH "$USER_@$ROBOT" 'test -f ~/snack_butler_config.json || echo "{}" > ~/snack_butler_config.json'

# 装过的才重启；没装的不在这儿建单元，只提示一声，免得掩盖「这台车压根没部署过」
for unit in jetson-agent webrtc-agent; do
  if $SSH "$USER_@$ROBOT" "systemctl list-unit-files $unit.service --no-legend | grep -q ." ; then
    $SSH "$USER_@$ROBOT" "sudo systemctl restart $unit"
    echo "== $unit 已重启"
  else
    echo "== $unit 未安装（跳过重启）"
  fi
done

echo "== 安装 systemd 服务"
$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/x11vnc.service >/dev/null <<'EOF'
[Unit]
Description=x11vnc VNC Server (auto-detect desktop display)
After=display-manager.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_
ExecStart=/home/$USER_/run_x11vnc.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF"

# 雷达不能按物理 USB 拓扑路径绑定；换 HUB 口或冷启动后路径会变化。
# A1 的 CH340 转串口用稳定 VID/PID 建 /dev/lidar，保证厂商 launch 与 watchdog 都能找到。
$SSH "$USER_@$ROBOT" "sudo tee /etc/udev/rules.d/99-jetrover-lidar.rules >/dev/null <<'EOF'
SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"1a86\", ATTRS{idProduct}==\"7523\", MODE:=\"0666\", GROUP:=\"dialout\", ENV{ID_MM_PORT_IGNORE}=\"1\", SYMLINK+=\"lidar\"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty --action=add
"
echo "== 雷达 udev 规则已更新（VID:PID 1a86:7523 -> /dev/lidar）"
# Hiwonder 的 ROS 环境变量(need_compile/HOST/MASTER)只在 ~/.zshrc 里设，
# 必须用 zsh -c 'source ~/.zshrc; ...' 起，用 bash+setup.bash 会报 KeyError 'need_compile'
$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/snack-butler.service >/dev/null <<'EOF'
[Unit]
Description=JetRover Visual Grasp (vision + arm pick-and-place)
After=start_app_node.service
Wants=start_app_node.service
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=notify
NotifyAccess=main
WatchdogSec=25
TimeoutStartSec=45
User=$USER_
WorkingDirectory=/home/$USER_
ExecStart=/usr/bin/zsh -c 'source /home/$USER_/.zshrc; exec python3 /home/$USER_/snack_butler.py'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/llm-agent.service >/dev/null <<'EOF'
[Unit]
Description=JetRover natural-language agent (Claude)
After=network-online.target

[Service]
Type=simple
User=$USER_
WorkingDirectory=/home/$USER_
EnvironmentFile=-/home/$USER_/.llm_agent.env
ExecStart=/usr/bin/python3 /home/$USER_/llm_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/explorer-agent.service >/dev/null <<'EOF'
[Unit]
Description=JetRover autonomous frontier explorer
After=start_app_node.service network-online.target
Wants=start_app_node.service
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=notify
NotifyAccess=main
WatchdogSec=25
TimeoutStartSec=45
User=$USER_
WorkingDirectory=/home/$USER_
ExecStart=/usr/bin/zsh -c 'source /home/$USER_/.zshrc; exec python3 /home/$USER_/explorer_agent.py'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/exploration-nav.service >/dev/null <<'EOF'
[Unit]
Description=JetRover online SLAM and Nav2 for autonomous exploration
After=start_app_node.service nav-safety.service network-online.target
Requires=start_app_node.service nav-safety.service

[Service]
Type=simple
User=$USER_
WorkingDirectory=/home/$USER_
ExecStart=/usr/bin/zsh /home/$USER_/run_exploration_nav.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/nav-safety.service >/dev/null <<'EOF'
[Unit]
Description=JetRover Nav2 motion safety guard
After=start_app_node.service
Requires=start_app_node.service
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=notify
NotifyAccess=main
WatchdogSec=20
TimeoutStartSec=30
User=$USER_
WorkingDirectory=/home/$USER_
ExecStart=/usr/bin/zsh -c 'source /home/$USER_/.zshrc; exec python3 /home/$USER_/nav_safety_guard.py'
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF"

$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/lidar-watchdog.service >/dev/null <<'EOF'
[Unit]
Description=JetRover lidar USB recovery watchdog
After=start_app_node.service

[Service]
Type=simple
User=$USER_
WorkingDirectory=/home/$USER_
ExecStart=/usr/bin/zsh -c 'source /home/$USER_/.zshrc; exec python3 /home/$USER_/lidar_watchdog.py'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

# 看门狗以普通用户运行，只允许重启这一项基础服务；不授予通用 systemctl/root 权限。
$SSH "$USER_@$ROBOT" "echo '$USER_ ALL=(root) NOPASSWD: /usr/bin/systemctl restart start_app_node.service' | sudo tee /etc/sudoers.d/jetrover-lidar-watchdog >/dev/null && sudo chmod 440 /etc/sudoers.d/jetrover-lidar-watchdog && sudo visudo -cf /etc/sudoers.d/jetrover-lidar-watchdog >/dev/null"

# 网页只能重启界面列出的 9 个自建服务；每条 sudo 命令都固定到完整 unit 参数。
$SSH "$USER_@$ROBOT" "sudo tee /etc/sudoers.d/jetrover-webctl >/dev/null <<'EOF'
Cmnd_Alias JETROVER_WEBCTL_RESTART = /usr/bin/systemctl restart webctl.service, /usr/bin/systemctl restart jetson-agent.service, /usr/bin/systemctl restart snack-butler.service, /usr/bin/systemctl restart explorer-agent.service, /usr/bin/systemctl restart exploration-nav.service, /usr/bin/systemctl restart nav-safety.service, /usr/bin/systemctl restart lidar-watchdog.service, /usr/bin/systemctl restart webrtc-agent.service, /usr/bin/systemctl restart llm-agent.service
$USER_ ALL=(root) NOPASSWD: JETROVER_WEBCTL_RESTART
EOF
sudo chmod 440 /etc/sudoers.d/jetrover-webctl
sudo visudo -cf /etc/sudoers.d/jetrover-webctl >/dev/null"

$SSH "$USER_@$ROBOT" 'sudo systemctl daemon-reload && sudo systemctl enable snack-butler lidar-watchdog nav-safety exploration-nav explorer-agent x11vnc && sudo systemctl restart snack-butler lidar-watchdog nav-safety exploration-nav explorer-agent x11vnc'
echo "== snack-butler / lidar-watchdog / nav-safety / exploration-nav / explorer-agent / x11vnc 已启动"
$SSH "$USER_@$ROBOT" 'systemctl is-active snack-butler || sudo journalctl -u snack-butler -n 30 --no-pager'

if $SSH "$USER_@$ROBOT" 'test -f ~/.llm_agent.env'; then
  $SSH "$USER_@$ROBOT" 'sudo systemctl enable --now llm-agent'
  echo "== llm-agent 已启动"
else
  cat <<'TIP'

== llm-agent 没启（缺 API key）。要用自然语言指令的话，在机器人上：
     pip3 install anthropic websocket-client
     echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/.llm_agent.env && chmod 600 ~/.llm_agent.env
     sudo systemctl enable --now llm-agent
TIP
fi

echo
echo "网页：http://$ROBOT:8000/"
