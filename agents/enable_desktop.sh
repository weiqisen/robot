#!/usr/bin/env bash
# 恢复 JetRover 7 英寸触摸屏的 GNOME 桌面。部署后位于 ~/enable_desktop.sh。
set -euo pipefail
if [ "${EUID}" -ne 0 ]; then exec sudo "$0" "$@"; fi
systemctl set-default graphical.target
systemctl start gdm.service
echo "GNOME 桌面已启用；下次开机也会进入图形桌面。"
