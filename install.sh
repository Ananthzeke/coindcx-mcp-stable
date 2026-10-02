#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if ! command -v uv >/dev/null 2>&1; then
    echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

uv sync --locked
if [[ ! -f .env ]]; then
    (umask 077; cp .env.example .env)
fi

echo "Installed. Public tools work immediately; add credentials to .env for account tools."
echo "Start the server with: uv run --locked --no-dev coindcx-mcp"
