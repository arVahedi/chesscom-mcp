#!/usr/bin/env bash
set -Eeuo pipefail

readonly token="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE"
readonly project_name="chess-com-mcp-smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"

export CHESS_COM_MCP_AUTH_TOKENS="{\"smoke-agent\":\"${token}\"}"

compose() {
    docker compose --project-name "${project_name}" "$@"
}

cleanup() {
    local exit_code=$?
    if [[ ${exit_code} -ne 0 ]]; then
        printf '%s\n' "--- Docker Compose logs ---"
        compose logs --no-color 2>/dev/null || true
    fi
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    exit "${exit_code}"
}
trap cleanup EXIT

compose config --quiet
if env -u CHESS_COM_MCP_AUTH_TOKENS \
    docker compose --project-name "${project_name}-missing-env" config >/dev/null 2>&1; then
    printf '%s\n' "Compose unexpectedly accepted missing required environment variables." >&2
    exit 1
fi

compose up --detach --build

readonly mcp_id="$(compose ps --quiet chess-com-mcp)"
[[ -n "${mcp_id}" ]]

for _ in $(seq 1 90); do
    mcp_health="$(docker inspect --format '{{.State.Health.Status}}' "${mcp_id}" 2>/dev/null || true)"
    if [[ "${mcp_health}" == "healthy" ]]; then
        break
    fi
    sleep 1
done
[[ "$(docker inspect --format '{{.State.Health.Status}}' "${mcp_id}")" == "healthy" ]]

[[ "$(docker inspect --format '{{.Config.User}}' "${mcp_id}")" == "10001:10001" ]]
[[ "$(docker port "${mcp_id}" 8765/tcp)" == "127.0.0.1:8765" ]]
[[ "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "${mcp_id}")" == "true" ]]

readonly curl_base=(
    curl --noproxy '*' --silent --show-error --max-time 5
)

"${curl_base[@]}" --fail "http://127.0.0.1:8765/healthz" | grep --fixed-strings '"status":"ok"' >/dev/null

missing_status="$("${curl_base[@]}" --output /dev/null --write-out '%{http_code}' \
    --header 'Content-Type: application/json' --data '{}' "http://127.0.0.1:8765/mcp")"
wrong_status="$("${curl_base[@]}" --output /dev/null --write-out '%{http_code}' \
    --header 'Authorization: Bearer wrong-token' --header 'Content-Type: application/json' \
    --data '{}' "http://127.0.0.1:8765/mcp")"
[[ "${missing_status}" == "401" && "${wrong_status}" == "401" ]]

initialize_response="$("${curl_base[@]}" --fail \
    --header "Authorization: Bearer ${token}" \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"compose-smoke","version":"1"}}}' \
    "http://127.0.0.1:8765/mcp")"
grep --fixed-strings '"name":"chess-com-mcp"' <<<"${initialize_response}" >/dev/null

unrelated_status="$("${curl_base[@]}" --output /dev/null --write-out '%{http_code}' \
    "http://127.0.0.1:8765/not-found")"
[[ "${unrelated_status}" == "404" ]]

printf '%s\n' "Docker Compose HTTP smoke test passed."
