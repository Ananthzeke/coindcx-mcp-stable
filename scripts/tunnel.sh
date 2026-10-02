#!/usr/bin/env bash
set -euo pipefail
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
profile_dir="$project_root/.local/tunnel-profiles"
key_file="$project_root/.local/openai-runtime-key"
client="$project_root/.local/tunnel-client/tunnel-client"
if [[ ! -x "$client" ]]; then
  client="$(command -v tunnel-client || true)"
fi
if [[ -z "$client" || ! -x "$client" ]]; then
  echo "Download the official tunnel-client from OpenAI Platform tunnel settings." >&2
  exit 1
fi

action="${1:-}"
case "$action" in
  init)
    if [[ $# -ne 2 || -z "$2" ]]; then
      echo "Usage: $0 init TUNNEL_ID" >&2
      exit 2
    fi
    # Quote the launcher path for the tunnel client's stdio command parser.
    launcher="$project_root/scripts/run-portfolio.sh"
    launcher="${launcher//\'/\'\\\'\'}"
    "$client" init \
      --sample sample_mcp_stdio_local \
      --profile coindcx-portfolio \
      --profile-dir "$profile_dir" \
      --tunnel-id "$2" \
      --control-plane-api-key-ref "file:$key_file" \
      --health-listen-addr 127.0.0.1:0 \
      --mcp-command "'$launcher'"
    ;;
  doctor|run)
    if [[ $# -ne 1 ]]; then
      echo "Usage: $0 $action" >&2
      exit 2
    fi
    if [[ ! -s "$key_file" ]]; then
      echo "Save your OpenAI runtime API key locally at: $key_file (permissions 600)." >&2
      echo "Do not paste credentials into chat." >&2
      exit 1
    fi
    options=(--profile coindcx-portfolio --profile-dir "$profile_dir")
    if [[ "$action" == "doctor" ]]; then
      options+=(--explain)
    fi
    exec "$client" "$action" "${options[@]}"
    ;;
  *)
    echo "Usage: $0 {init TUNNEL_ID|doctor|run}" >&2
    exit 2
    ;;
esac
