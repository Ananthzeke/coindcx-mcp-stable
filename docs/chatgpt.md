# Connect CoinDCX Portfolio to ChatGPT

The server runs locally over stdio. OpenAI's [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) supports this transport without exposing a public server port. ChatGPT receives the account data returned by tools it calls. This connection is for your own workspace.

## Prepare the server

From the project directory:

```sh
uv sync --locked
```

Configure `COINDCX_API_KEY` and `COINDCX_SECRET_KEY` in the existing `.env`. Keep credentials local. Public market tools do not require credentials. The tunnel must use `scripts/run-portfolio.sh`, which enforces read-only access regardless of other settings.

## Create a tunnel

Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels), create `CoinDCX Portfolio`, and associate it with both your Platform organization and the ChatGPT workspace that will use it. Copy its tunnel ID. Download the official tunnel client using the link on that page.

Creating/editing tunnels requires Tunnels Read + Manage. Running a client requires Read + Use. ChatGPT developer-mode access is a separate permission. A workspace administrator may need to grant it.

## Configure the local client with the helper

The helper uses a local OpenAI runtime key file at `.local/openai-runtime-key`. This key is separate from your CoinDCX credentials. Save it with file permissions `600`; do not paste keys into chat or commit them. `.local/` is ignored by Git. The official client can be on your PATH or installed at `.local/tunnel-client/tunnel-client` with its release companions beside it.

From the project directory, replace the tunnel ID below:

```sh
./scripts/tunnel.sh init YOUR_TUNNEL_ID
./scripts/tunnel.sh doctor
./scripts/tunnel.sh run
```

The helper creates a local profile with an absolute portfolio launcher path, a file reference for the key, and a loopback-only health/admin listener on an available port. It does not overwrite existing profiles. No key is embedded in the profile. Keep the computer awake and the client running while ChatGPT uses the tools. This launcher does not start itself on login. A running tunnel is required for discovery and calls.

## Add the ChatGPT plugin

Following the [official plugin quickstart](https://developers.openai.com/plugins/quickstart):

1. Enable **Settings → Security and login → Developer mode** in ChatGPT.
2. Open [ChatGPT Plugins](https://chatgpt.com/plugins), click **+**, and choose **Tunnel** under Connection.
3. Select the tunnel or enter its ID. Name the plugin **CoinDCX Portfolio**.
4. Install it from your personal plugins, start a **Work** chat, and use `@` to select it.
5. Verify that balances and positions work and that trading/transfer tools are absent. There should be 27 read-only tools.

## What the tools can establish

Balances, wallet details, positions, trade history, and market prices can support a portfolio snapshot and allocation analysis. An executed-trade history page may not establish complete cost basis: pagination, transfers, external purchases, and fees can affect it. Ask for the data timestamp, valuation currency, missing inputs, and any assumptions in an analysis.

## Troubleshooting

- A missing tunnel in ChatGPT usually requires checking workspace association and Tunnels Read + Use permission.
- If discovery fails, ensure the tunnel client is running and the installed `.venv/bin/coindcx-mcp` command exists.
- Missing account credentials produce a tool error; public prices can still work.
- Restart the connection after changing configuration or upgrading the server.
- Logs and tool errors omit credentials. Avoid enabling raw HTTP/debug logging for account sessions.
