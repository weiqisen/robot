#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
runtime_dir="$HOME/Library/Application Support/JetroverRecorder"
log_dir="$HOME/Library/Logs"
agent_dir="$HOME/Library/LaunchAgents"
agent_plist="$agent_dir/com.jetrover.recorder.plist"

if [[ ! -f "$repo_dir/.mysql.env" ]]; then
  echo "缺少 $repo_dir/.mysql.env" >&2
  exit 1
fi

mkdir -p "$runtime_dir" "$log_dir" "$agent_dir"
cp "$repo_dir/tools/mac_recorder.py" "$runtime_dir/mac_recorder.py"
cp "$repo_dir/tools/run_mac_recorder.sh" "$runtime_dir/run_mac_recorder.sh"
cp "$repo_dir/.mysql.env" "$runtime_dir/.mysql.env"
chmod 700 "$runtime_dir/run_mac_recorder.sh"
chmod 600 "$runtime_dir/.mysql.env"

if [[ ! -x "$runtime_dir/.venv/bin/python" ]]; then
  /opt/homebrew/bin/python3 -m venv "$runtime_dir/.venv"
fi
"$runtime_dir/.venv/bin/python" -m pip install --quiet --disable-pip-version-check \
  websocket-client mysql-connector-python

sed \
  -e "s|__RUNTIME_DIR__|$runtime_dir|g" \
  -e "s|__LOG_DIR__|$log_dir|g" \
  "$repo_dir/tools/com.jetrover.recorder.plist" > "$agent_plist"
plutil -lint "$agent_plist"

launchctl bootout "gui/$(id -u)" "$agent_plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$agent_plist"
launchctl kickstart -k "gui/$(id -u)/com.jetrover.recorder"
echo "Mac 采集器已安装并启动：$runtime_dir"
