#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
server_command="$project_root/.venv/bin/coindcx-mcp"
if [[ ! -x "$server_command" ]]; then
  echo "Install dependencies first: uv --directory \"$project_root\" sync --locked" >&2
  exit 1
fi

# The CLI flag overrides process and .env settings. stdout belongs to MCP only.
exec "$server_command" --read-only
