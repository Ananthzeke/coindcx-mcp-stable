#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
server_command="$project_root/.venv/bin/coindcx-mcp"
if [[ ! -x "$server_command" ]]; then
  echo "Install dependencies first: uv --directory \"$project_root\" sync --locked" >&2
  exit 1
fi

# Keep the cap fixed for this desktop connection, even if .env has another value.
export COINDCX_MAX_SPOT_ORDER_INR=500
exec "$server_command" --spot-trading
