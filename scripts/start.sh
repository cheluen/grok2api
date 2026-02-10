#!/usr/bin/env sh
set -eu

# Hugging Face Spaces 会注入 PORT=7860；同时兼容项目既有的 SERVER_* 变量。
HOST="${SERVER_HOST:-0.0.0.0}"
PORT_VALUE="${SERVER_PORT:-${PORT:-8000}}"
WORKERS="${SERVER_WORKERS:-1}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# uvicorn 的 log-level 更偏好小写
LOG_LEVEL_LOWER="$(printf '%s' "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')"

exec uvicorn main:app \
  --host "$HOST" \
  --port "$PORT_VALUE" \
  --workers "$WORKERS" \
  --log-level "$LOG_LEVEL_LOWER"

