#!/usr/bin/env bash
# 把零食管家部署到 JetRover。机器人常因电量低反复断电，所以默认「蹲守」：
# 一直等到 SSH 通了再推送，不用守着开机。
#
#   ./agents/deploy_snack.sh                  # 蹲守 + 部署代码和网页
#   ROBOT=192.168.3.63 ./agents/deploy_snack.sh
#   NO_WAIT=1 ./agents/deploy_snack.sh        # 机器人已在线，别等
#   WEB_ONLY=1 ./agents/deploy_snack.sh       # 只推网页
set -euo pipefail

ROBOT="${ROBOT:-192.168.3.63}"
USER_="${ROBOT_USER:-ubuntu}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5"
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
tar -C "$HERE/studio-vue/dist" -czf /tmp/webctl.tgz .
$SCP /tmp/webctl.tgz "$USER_@$ROBOT:/tmp/"
$SSH "$USER_@$ROBOT" 'mkdir -p ~/web_control && tar -C ~/web_control -xzf /tmp/webctl.tgz && rm /tmp/webctl.tgz'
[ -n "${WEB_ONLY:-}" ] && { echo "== 只推网页，完成"; exit 0; }

echo "== 推送 agents"
$SCP "$HERE"/agents/{snack_butler.py,arm_kinematics.py,vision_geometry.py,snack_detector.py,llm_agent.py} \
     "$USER_@$ROBOT:~/"
# 配置文件已存在就不覆盖——上面标定出来的参数在里面
$SSH "$USER_@$ROBOT" 'test -f ~/snack_butler_config.json || echo "{}" > ~/snack_butler_config.json'

echo "== 安装 systemd 服务"
# Hiwonder 的 ROS 环境变量(need_compile/HOST/MASTER)只在 ~/.zshrc 里设，
# 必须用 zsh -c 'source ~/.zshrc; ...' 起，用 bash+setup.bash 会报 KeyError 'need_compile'
$SSH "$USER_@$ROBOT" "sudo tee /etc/systemd/system/snack-butler.service >/dev/null <<'EOF'
[Unit]
Description=JetRover Snack Butler (vision + arm pick-and-place)
After=start_app_node.service
Wants=start_app_node.service

[Service]
Type=simple
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

$SSH "$USER_@$ROBOT" 'sudo systemctl daemon-reload && sudo systemctl enable --now snack-butler'
echo "== snack-butler 已启动"
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
echo "网页：http://$ROBOT:8000/#snack"
