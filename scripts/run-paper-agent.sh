#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$project_root/.venv/bin/python" ]]; then
  echo "Install dependencies first: uv --directory \"$project_root\" sync --locked" >&2
  exit 1
fi
cd -- "$project_root"
exec "$project_root/.venv/bin/python" -m coindcx_mcp.paper_agent "$@"
