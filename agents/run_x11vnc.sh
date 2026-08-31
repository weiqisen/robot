#!/usr/bin/env bash
# GDM 登录后真实桌面不保证是 :0（本机曾变成 :1）。逐个验证 X socket，找到
# 当前 ubuntu 用户真正能打开的显示后再启动 x11vnc，避免 -loop 外壳假装 active。
set -euo pipefail

VNC_PASS_FILE="${VNC_PASS_FILE:-/home/ubuntu/.vnc/passwd}"
while true; do
  for socket in /tmp/.X11-unix/X*; do
    [ -S "$socket" ] || continue
    number="${socket##*/X}"
    display=":$number"
    for auth in /run/user/1000/gdm/Xauthority /home/ubuntu/.Xauthority; do
      [ -r "$auth" ] || continue
      if DISPLAY="$display" XAUTHORITY="$auth" xdpyinfo >/dev/null 2>&1; then
        echo "[x11vnc] using display=$display auth=$auth"
        exec /usr/bin/x11vnc -display "$display" -auth "$auth" \
          -rfbauth "$VNC_PASS_FILE" -rfbport 5900 -forever -noxdamage -repeat -shared -nap
      fi
    done
  done
  echo "[x11vnc] waiting for an accessible desktop display" >&2
  sleep 2
done
