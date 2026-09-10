#!/usr/bin/env bash
# 恢复自主探索 / SLAM / Nav2。nav-safety 始终独立运行，控制路径不被绕过。
set -euo pipefail
if [ "${EUID}" -ne 0 ]; then exec sudo "$0" "$@"; fi
systemctl enable --now exploration-nav.service explorer-agent.service
echo "自主导航栈已恢复。"
