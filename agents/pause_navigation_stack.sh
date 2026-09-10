#!/usr/bin/env bash
# 暂停自主探索 / SLAM / Nav2，保留相机、抓取、雷达看门狗及速度安全闸门。
set -euo pipefail
if [ "${EUID}" -ne 0 ]; then exec sudo "$0" "$@"; fi
systemctl disable --now explorer-agent.service exploration-nav.service
echo "自主导航栈已暂停；约可释放 1 GB 内存。"
