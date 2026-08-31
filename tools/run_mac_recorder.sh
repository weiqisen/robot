#!/usr/bin/env bash
set -euo pipefail
runtime_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$runtime_dir"
set -a
source .mysql.env
set +a
exec .venv/bin/python mac_recorder.py
