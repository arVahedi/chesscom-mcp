#!/usr/bin/env bash
set -Eeuo pipefail

readonly public_host="chess-mcp.home.arpa"
readonly token="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE"
readonly project_name="chess-com-mcp-smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
readonly work_dir="$(mktemp -d)"

export CHESS_COM_MCP_PUBLIC_HOST="${public_host}"
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
    rm -rf "${work_dir}"
    exit "${exit_code}"
}
trap cleanup EXIT

compose config --quiet
if env -u CHESS_COM_MCP_PUBLIC_HOST -u CHESS_COM_MCP_AUTH_TOKENS \
    docker compose --project-name "${project_name}-missing-env" config >/dev/null 2>&1; then
    printf '%s\n' "Compose unexpectedly accepted missing required environment variables." >&2
    exit 1
fi

compose up --detach --build

readonly mcp_id="$(compose ps --quiet chess-com-mcp)"
readonly caddy_id="$(compose ps --quiet caddy)"
[[ -n "${mcp_id}" && -n "${caddy_id}" ]]

for _ in $(seq 1 90); do
    mcp_health="$(docker inspect --format '{{.State.Health.Status}}' "${mcp_id}" 2>/dev/null || true)"
    caddy_health="$(docker inspect --format '{{.State.Health.Status}}' "${caddy_id}" 2>/dev/null || true)"
    if [[ "${mcp_health}" == "healthy" && "${caddy_health}" == "healthy" ]]; then
        break
    fi
    sleep 1
done
[[ "$(docker inspect --format '{{.State.Health.Status}}' "${mcp_id}")" == "healthy" ]]
[[ "$(docker inspect --format '{{.State.Health.Status}}' "${caddy_id}")" == "healthy" ]]

[[ "$(docker inspect --format '{{.Config.User}}' "${mcp_id}")" == "10001:10001" ]]
[[ "$(docker inspect --format '{{json .HostConfig.PortBindings}}' "${mcp_id}")" == "{}" ]]
[[ "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "${mcp_id}")" == "true" ]]

compose cp caddy:/data/caddy/pki/authorities/local/root.crt "${work_dir}/root.crt"
readonly curl_base=(
    curl --noproxy '*' --silent --show-error --max-time 5
    --cacert "${work_dir}/root.crt"
    --resolve "${public_host}:443:127.0.0.1"
)

"${curl_base[@]}" --fail "https://${public_host}/healthz" | grep --fixed-strings '"status":"ok"' >/dev/null

missing_status="$("${curl_base[@]}" --output /dev/null --write-out '%{http_code}' \
    --header 'Content-Type: application/json' --data '{}' "https://${public_host}/mcp")"
wrong_status="$("${curl_base[@]}" --output /dev/null --write-out '%{http_code}' \
    --header 'Authorization: Bearer wrong-token' --header 'Content-Type: application/json' \
    --data '{}' "https://${public_host}/mcp")"
[[ "${missing_status}" == "401" && "${wrong_status}" == "401" ]]

initialize_response="$("${curl_base[@]}" --fail \
    --header "Authorization: Bearer ${token}" \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"compose-smoke","version":"1"}}}' \
    "https://${public_host}/mcp")"
grep --fixed-strings '"name":"chess-com-mcp"' <<<"${initialize_response}" >/dev/null

unrelated_status="$("${curl_base[@]}" --output /dev/null --write-out '%{http_code}' \
    "https://${public_host}/not-found")"
[[ "${unrelated_status}" == "404" ]]

printf '%s\n' "Docker Compose HTTPS smoke test passed."
