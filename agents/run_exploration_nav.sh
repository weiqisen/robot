#!/usr/bin/env zsh
# Jetson 单独供电时不加载高开销的 SLAM/Nav2；完整底盘上电、雷达枚举后自动启动。
# 厂商 .robotrc 会在赋默认值前读取 LD_LIBRARY_PATH，不能在 source 前开启 nounset，
# 否则冷启动时 zsh 会以 126 退出，SLAM/Nav2 就会陷入 systemd 重启循环。
set -e
while [[ ! -e /dev/lidar ]]; do
  sleep 5
done
source /home/ubuntu/.zshrc
set -u
exec python3 /home/ubuntu/exploration_bringup.launch.py
