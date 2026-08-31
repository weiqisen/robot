#!/usr/bin/env bash
# JetRover 一键部署入口。
# 默认构建当前工作区的最新前端和机器人端程序，并完整同步到小车。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
用法：
  ./deploy.sh                         完整部署，离线时等待小车上线
  ./deploy.sh --no-wait               小车应已在线，连接失败立即退出
  ./deploy.sh --web-only              只更新网页和 webctl
  ./deploy.sh --robot 192.168.3.99    临时指定小车地址

也支持 .robot.env 及 ROBOT、ROBOT_USER、ROBOT_PASS、NO_WAIT、WEB_ONLY 环境变量。
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-wait) export NO_WAIT=1; shift ;;
    --web-only) export WEB_ONLY=1; shift ;;
    --robot)
      [ "$#" -ge 2 ] || { echo "错误：--robot 后需要 IP 或主机名" >&2; exit 2; }
      export ROBOT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "错误：未知参数 $1" >&2; usage >&2; exit 2 ;;
  esac
done

echo "== JetRover 一键部署"
exec "$ROOT/agents/deploy_snack.sh"
