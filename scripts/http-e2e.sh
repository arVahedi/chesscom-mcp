#!/usr/bin/env bash
set -Eeuo pipefail

readonly host="127.0.0.1:8765"
readonly token="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE"
readonly work_dir="$(mktemp -d)"
server_pid=""

cleanup() {
    local exit_code=$?
    if [[ -n "${server_pid}" ]] && kill -0 "${server_pid}" 2>/dev/null; then
        kill "${server_pid}"
        wait "${server_pid}" 2>/dev/null || true
    fi
    if [[ ${exit_code} -ne 0 ]]; then
        printf '%s\n' "--- MCP server log ---"
        sed -n '1,240p' "${work_dir}/server.log" 2>/dev/null || true
    fi
    rm -rf "${work_dir}"
    exit "${exit_code}"
}
trap cleanup EXIT

export CHESS_COM_MCP_AUTH_TOKENS="{\"e2e-agent\":\"${token}\"}"
export CHESS_COM_MCP_ALLOWED_HOSTS="${host}"
export CHESS_COM_MCP_BIND_HOST="127.0.0.1"

.venv/bin/chess-com-mcp --transport http >"${work_dir}/server.log" 2>&1 &
server_pid=$!

for _ in $(seq 1 30); do
    if curl --silent --fail --max-time 2 "http://${host}/healthz" >/dev/null; then
        break
    fi
    sleep 1
done
curl --silent --fail --max-time 2 "http://${host}/healthz" | grep --fixed-strings '"status":"ok"' >/dev/null

missing_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 \
    --header 'Content-Type: application/json' --data '{}' "http://${host}/mcp")"
wrong_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 \
    --header 'Authorization: Bearer wrong-token' --header 'Content-Type: application/json' \
    --data '{}' "http://${host}/mcp")"
[[ "${missing_status}" == "401" && "${wrong_status}" == "401" ]]

initialize_response="$(curl --silent --show-error --fail --max-time 5 \
    --header "Authorization: Bearer ${token}" \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"native-e2e","version":"1"}}}' \
    "http://${host}/mcp")"
grep --fixed-strings '"name":"chess-com-mcp"' <<<"${initialize_response}" >/dev/null

tools_response="$(curl --silent --show-error --fail --max-time 5 \
    --header "Authorization: Bearer ${token}" \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --header 'MCP-Protocol-Version: 2025-11-25' \
    --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
    "http://${host}/mcp")"
grep --fixed-strings '"get_player_profile"' <<<"${tools_response}" >/dev/null
grep --fixed-strings '"get_club_members"' <<<"${tools_response}" >/dev/null

invalid_call_response="$(curl --silent --show-error --fail --max-time 5 \
    --header "Authorization: Bearer ${token}" \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --header 'MCP-Protocol-Version: 2025-11-25' \
    --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_player_profile","arguments":{"username":"../../etc/passwd"}}}' \
    "http://${host}/mcp")"
grep --fixed-strings '"isError":true' <<<"${invalid_call_response}" >/dev/null
grep --fixed-strings '"invalid_input"' <<<"${invalid_call_response}" >/dev/null

printf '%s\n' "Native HTTP MCP end-to-end test passed."
