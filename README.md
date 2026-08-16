# Chess.com Personal MCP Server

[![CI](https://github.com/arVahedi/chesscom-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/arVahedi/chesscom-mcp/actions/workflows/ci.yml)
[![Live integration](https://github.com/arVahedi/chesscom-mcp/actions/workflows/live-integration.yml/badge.svg)](https://github.com/arVahedi/chesscom-mcp/actions/workflows/live-integration.yml)

A stateless, read-only MCP gateway for the public [Chess.com Published Data API](https://www.chess.com/news/view/published-data-api). It gives Codex or another trusted agent a small typed tool surface without storing Chess.com credentials, cookies, sessions, API keys, games, or query history.

```text
Agent -> authenticated HTTP on localhost -> MCP container -> HTTPS -> api.chess.com/pub
```

The primary transport is stateless Streamable HTTP with JSON responses. Local stdio is the default CLI transport. Remote Chess.com strings are returned as untrusted external data and are never treated as instructions or followed as URLs.

## Tools

| Tool | Purpose |
| --- | --- |
| `get_player_profile(username)` | Public player profile |
| `get_player_stats(username)` | Public player statistics |
| `is_player_online(username)` | Current online status |
| `get_player_current_daily_games(username, offset=0, limit=25)` | Paginated current Daily games |
| `get_player_game_archives(username)` | Validated `{year, month}` archive entries |
| `get_player_games_by_month(username, year, month, offset=0, limit=25)` | Paginated monthly games without embedded PGN |
| `get_player_games_pgn_by_month(username, year, month, offset_chars=0, max_chars=50000)` | Segmented monthly PGN text |
| `get_titled_players(title, offset=0, limit=100)` | Paginated titled-player names |
| `get_club_profile(url_id)` | Public club profile |
| `get_club_members(url_id, category="all_time", offset=0, limit=100)` | Paginated club members |

All endpoints and the upstream hostname are constructed internally. There is no tool accepting a URL, host, endpoint, filesystem path, or command.

## Native installation

Python packages must be installed only in a virtual environment. Python 3.12 or newer is required.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip install --require-hashes -r requirements-build.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
```

Run the local stdio server:

```sh
.venv/bin/chess-com-mcp
```

For direct HTTP on loopback, generate a token and set the required exact Host value:

```sh
MCP_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export MCP_TOKEN
export CHESS_COM_MCP_AUTH_TOKENS="$(.venv/bin/python -c 'import json,os; print(json.dumps({"codex-local": os.environ["MCP_TOKEN"]}))')"
export CHESS_COM_MCP_ALLOWED_HOSTS=127.0.0.1:8765
.venv/bin/chess-com-mcp --transport http
```

The raw HTTP listener has no TLS. Keep it on loopback unless a trusted TLS reverse proxy protects it.

## Configuration

| Variable | Default | Rules |
| --- | --- | --- |
| `CHESS_COM_MCP_TRANSPORT` | `stdio` | `stdio` or `http`; `--transport` overrides it |
| `CHESS_COM_MCP_BIND_HOST` | `127.0.0.1` | IPv4 or IPv6 literal only; hostnames and interface names are rejected |
| `CHESS_COM_MCP_PORT` | `8765` | `1024..65535` |
| `CHESS_COM_MCP_AUTH_TOKENS` | unset | HTTP requires a nonempty JSON map; each unpadded base64url token must decode to at least 32 bytes |
| `CHESS_COM_MCP_ALLOWED_HOSTS` | unset | HTTP requires comma-separated exact Host header values; no wildcard |
| `CHESS_COM_MCP_ALLOWED_ORIGINS` | unset | Optional comma-separated exact `http://` or `https://` origins; a missing Origin is accepted |
| `CHESS_COM_MCP_TIMEOUT_SECONDS` | `20` | `1..60` seconds |
| `CHESS_COM_MCP_MAX_RESPONSE_BYTES` | `10485760` | Decoded upstream response ceiling, `65536..10485760` bytes |
| `CHESS_COM_MCP_LOG_LEVEL` | `WARNING` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

Agent names may contain ASCII letters, digits, `_`, and `-`, with length `1..50`. Tokens must be unique. Every configured agent has the same read-only permissions. Tokens are accepted only in the `Authorization: Bearer ...` header and every `/mcp` request is authenticated. `/healthz` is intentionally unauthenticated and always returns `{"status":"ok"}`.

Binding to `0.0.0.0`, `::`, or any other non-loopback address emits a warning because the internal listener is plaintext HTTP. HTTP startup fails closed when either authentication tokens or the Host allowlist is absent.

## Docker image

Build the digest-pinned, multi-stage image locally:

```sh
docker build -t chess-com-mcp:local .
```

The final image runs as UID/GID `10001`, contains only runtime dependencies, removes Python and operating-system package managers, and defaults to `chess-com-mcp --transport http`. Override the command to use stdio or other supported CLI arguments.

## Docker Compose on localhost

Generate a bearer token and supply its agent map from the invoking shell; do not commit it to a file:

```sh
MCP_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export MCP_TOKEN
export CHESS_COM_MCP_AUTH_TOKENS="$(.venv/bin/python -c 'import json,os; print(json.dumps({"codex-local": os.environ["MCP_TOKEN"]}))')"
docker compose up --build -d
```

The supplied `docker-compose.yml` starts only `chess-com-mcp`. The process binds `0.0.0.0:8765` inside the container, while Docker publishes it only to `127.0.0.1:8765` on the host. The MCP endpoint is therefore `http://127.0.0.1:8765/mcp`; it is not reachable from other LAN devices. Bearer authentication remains mandatory because the connection is unencrypted HTTP. Reverse proxies and TLS termination are infrastructure concerns and can be supplied separately according to the user's environment.

The application constructs requests only below `https://api.chess.com/pub`, uses GET, verifies TLS, ignores proxy environment variables, refuses redirects, and bounds concurrency, retries, time, and decoded bytes. If the Docker host needs a network-level outbound allowlist in addition to this application boundary, enforce TCP 443 access to Chess.com's API at the host firewall or egress gateway.

## Codex configuration

Export the token on the Codex device under a dedicated environment variable, then add the server to `~/.codex/config.toml`:

```sh
export CHESS_COM_MCP_TOKEN='the-token-for-this-agent'
```

```toml
[mcp_servers.chess_com]
url = "http://127.0.0.1:8765/mcp"
bearer_token_env_var = "CHESS_COM_MCP_TOKEN"
required = true
```

Restart Codex after changing its environment or MCP configuration. This follows the [official Codex MCP configuration](https://developers.openai.com/codex/mcp). Never put the token in the URL, TOML file, command-line arguments, cookies, or source control.

For local stdio instead:

```toml
[mcp_servers.chess_com_local]
command = "/absolute/path/to/chesscom-mcp/.venv/bin/chess-com-mcp"
```

### Rotation and revocation

Generate a different random token for each agent. To rotate one agent, replace only that map entry in the host environment and recreate the MCP container. To revoke an agent, remove its entry and recreate the container:

```sh
docker compose up -d --force-recreate chess-com-mcp
```

Treat the environment of the Docker host and Codex process as secret-bearing. Avoid `.env` files, shell history, logs, screenshots, and process arguments that disclose tokens.

## Development and verification

Install development tooling in the same project virtual environment:

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
```

Run the offline checks:

```sh
.venv/bin/ruff format --check src tests     # Verifies source and test files follow Ruff formatting without modifying them.
.venv/bin/ruff check src tests              # Checks source and test files for linting errors and unsafe patterns.
.venv/bin/mypy src                          # Statically checks type annotations in the source code.
PYTHONPATH=src .venv/bin/pytest --cov=chess_com_mcp --cov-report=term-missing       # Runs tests and reports coverage, including untested lines.
.venv/bin/pip-audit -r requirements.txt     # Checks production dependencies for known security vulnerabilities.
```

The live Chess.com smoke test is opt-in and performs a real public API request:

```sh
CHESS_COM_MCP_RUN_INTEGRATION=1 PYTHONPATH=src .venv/bin/pytest -m live tests/test_integration.py
```

### Continuous integration

GitHub Actions runs workflow validation, formatting, linting, strict type checking, package building, dependency auditing, unit tests, offline integration tests, a native HTTP end-to-end test, and a Docker Compose HTTP smoke test for every pull request and push to `main`. It also enforces the 90% coverage threshold, writes a coverage table to the workflow summary, and uploads XML, HTML, and JUnit reports for 14 days. The live Chess.com test runs after pushes to `main`, every Monday, or manually.

In the GitHub branch-protection rules for `main`, mark the CI quality, unit, integration, coverage, end-to-end, and smoke jobs as required before merging. Keep the live integration workflow post-merge because it intentionally depends on an external service.

Regenerate lock files only from the virtual environment after intentionally updating the corresponding `.in` file:

```sh
.venv/bin/pip-compile --generate-hashes --resolver=backtracking --output-file=requirements.txt requirements.in
.venv/bin/pip-compile --generate-hashes --allow-unsafe --resolver=backtracking --output-file=requirements-build.txt requirements-build.in
.venv/bin/pip-compile --generate-hashes --allow-unsafe --resolver=backtracking --output-file=requirements-dev.txt requirements-dev.in
```

Expected upstream failures become safe structured MCP errors. Successful results use a stable `ok`, `source`, `untrusted_external_data`, `data`, and optional pagination envelope. The server does not cache, persist, or log returned Chess.com content.

## License

[MIT](LICENSE)
