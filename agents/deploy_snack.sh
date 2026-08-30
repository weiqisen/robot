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
$SCP "$HERE"/agents/{snack_butler.py,arm_kinematics.py,vision_geometry.py,snack_detector.py,llm_agent.py,jetson_agent.py,webrtc_agent.py} \
     "$USER_@$ROBOT:~/"
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
