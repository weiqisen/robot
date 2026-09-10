#!/usr/bin/env bash
# 关闭 GNOME 桌面以释放 Jetson CPU/内存。部署后位于 ~/disable_desktop.sh。
set -euo pipefail
if [ "${EUID}" -ne 0 ]; then exec sudo "$0" "$@"; fi
systemctl set-default multi-user.target
systemctl stop gdm.service
echo "GNOME 桌面已关闭；下次开机将进入无桌面模式。"
