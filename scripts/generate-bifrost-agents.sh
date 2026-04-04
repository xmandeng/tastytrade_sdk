#!/usr/bin/env bash
# generate-bifrost-agents.sh — Query Bifrost gateways and generate subagent definitions
#
# Usage:
#   ./scripts/generate-bifrost-agents.sh                    # Generate all agents
#   ./scripts/generate-bifrost-agents.sh --list-tools       # List available tools by prefix
set -euo pipefail

AGENTS_DIR=".claude/agents"
HEADERS_DIR=".claude/agent-headers"
mkdir -p "$AGENTS_DIR"

# Agent registry: agent_name|gateway_url_env|prefix_filter|transport
# prefix_filter: tool name prefix to include (e.g., "github", "jira", "playwright")
AGENTS=(
  "jira-workflow|BIFROST_DEV_URL|jira|stateless"
  "github-workflow|BIFROST_DEV_URL|github|stateless"
  "ui-tester|BIFROST_DESIGN_URL|playwright|stateless"
)

generate_tool_section() {
  local response="$1" prefix="$2"

  echo "$response" | jq -r --arg prefix "$prefix" \
    '.result.tools[] | select(.name | startswith($prefix)) | @base64' | while read -r tool_b64; do
    local tool_name tool_desc tool_schema required_fields optional_fields
    tool_name=$(echo "$tool_b64" | base64 -d | jq -r '.name')
    tool_desc=$(echo "$tool_b64" | base64 -d | jq -r '.description')
    tool_schema=$(echo "$tool_b64" | base64 -d | jq '.inputSchema')
    required_fields=$(echo "$tool_schema" | jq -r '(.required // []) | join(", ")')
    optional_fields=$(echo "$tool_schema" | jq -r 'if .properties then [.properties | to_entries[] | select(.key as $k | ('"$(echo "$tool_schema" | jq -c '.required // []')"' | index($k)) == null) | .key] | join(", ") else "" end')

    cat <<TOOL
### \`$tool_name\`

$tool_desc
Required: $required_fields
Optional: $optional_fields

<details><summary>Full schema</summary>

\`\`\`json
$(echo "$tool_schema" | jq '.')
\`\`\`

</details>

TOOL
  done
}

generate_agent() {
  local agent_name="$1" url="$2" prefix="$3" transport="$4"
  local url_env_name="BIFROST_${url##*_}"

  echo "Generating $agent_name (prefix: $prefix, gateway: $url) ..."

  # Health check
  if ! curl -sf "$url/health" >/dev/null 2>&1; then
    echo "ERROR: Gateway not healthy at $url/health" >&2
    return 1
  fi

  # Fetch tool manifest
  local response
  response=$(curl -sf -X POST "$url/mcp" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')

  local tool_count
  tool_count=$(echo "$response" | jq --arg prefix "$prefix" \
    '[.result.tools[] | select(.name | startswith($prefix))] | length')
  echo "  Found $tool_count $prefix tools"

  local outfile="$AGENTS_DIR/${agent_name}.md"
  local header_file="$HEADERS_DIR/${agent_name}.md"

  {
    # If a hand-maintained header exists, use it; otherwise generate a minimal one
    if [ -f "$header_file" ]; then
      cat "$header_file"
    else
      cat <<FRONTMATTER
---
name: ${agent_name}
description: Handles ${prefix} operations via Bifrost gateway
tools: Bash
---

You are a tool-calling agent. You execute operations by calling MCP tools through the Bifrost gateway via curl.
FRONTMATTER
    fi

    # Gateway info
    cat <<GATEWAY

## Gateway

- URL: $url
- Transport: $transport

## Available Tools (${tool_count} ${prefix} tools)

GATEWAY

    # Generate tool entries filtered by prefix
    generate_tool_section "$response" "$prefix"

    # Invocation pattern
    cat <<INVOKE
## Invocation Pattern

To call a tool, use this curl pattern via Bash:

\`\`\`bash
RESULT=\$(curl -sf -X POST "$url/mcp" \\
  -H "Content-Type: application/json" \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"TOOL_NAME","arguments":{...}}}')
echo "\$RESULT" | jq -r '.result.content[0].text // .error.message'
\`\`\`

Replace \`TOOL_NAME\` with the tool name from the manifest above. Replace \`{...}\` with a JSON object matching the tool's schema.

INVOKE

    # Response handling + contract
    cat <<'RESPONSE'
## Response Handling

1. Parse the JSON response from curl
2. If `.error` field present: report the error type and message
3. If `.result.content` present: extract by content type:
   - `text`: use `.result.content[0].text` directly
   - `image`: handle as base64
   - `resource`: handle as URI reference

## Response Contract

Always end your final response with a JSON status block:

On success:
```json
{"status": "success", "tools_called": ["tool_name"], "summary": "..."}
```

On error:
```json
{"status": "error", "error_type": "execution|gateway_timeout|protocol", "detail": "..."}
```

If you cannot produce the status block, end with a clear natural language summary instead. The primary agent will parse the JSON block if present, or reason over your full text response if not.
RESPONSE

  } > "$outfile"

  echo "  Generated $outfile ($tool_count tools)"
}

# Handle --list-tools flag
if [ "${1:-}" = "--list-tools" ]; then
  for entry in "${AGENTS[@]}"; do
    IFS='|' read -r agent_name url_env prefix transport <<< "$entry"
    url="${!url_env:-}"
    [ -z "$url" ] && continue
    echo "=== $agent_name ($prefix) ==="
    curl -sf -X POST "$url/mcp" \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
      | jq -r --arg prefix "$prefix" '.result.tools[] | select(.name | startswith($prefix)) | .name'
    echo
  done
  exit 0
fi

# Main: generate all agents
for entry in "${AGENTS[@]}"; do
  IFS='|' read -r agent_name url_env prefix transport <<< "$entry"
  url="${!url_env:-}"
  if [ -z "$url" ]; then
    echo "SKIP: $agent_name — \$$url_env not set" >&2
    continue
  fi
  generate_agent "$agent_name" "$url" "$prefix" "$transport"
done

echo "Done."
