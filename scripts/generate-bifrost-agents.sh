#!/usr/bin/env bash
# generate-bifrost-agents.sh — Query Bifrost gateways and generate subagent definitions
# Usage: ./scripts/generate-bifrost-agents.sh
set -euo pipefail

AGENTS_DIR=".claude/agents"
mkdir -p "$AGENTS_DIR"

# Gateway registry: name|url_env|transport
GATEWAYS=(
  "dev|BIFROST_DEV_URL|stateless"
)

generate_agent() {
  local name="$1" url="$2" transport="$3"

  echo "Querying $name gateway at $url ..."

  # Health check
  if ! curl -sf "$url/health" >/dev/null 2>&1; then
    echo "ERROR: $name gateway not healthy at $url/health" >&2
    return 1
  fi

  # Fetch tool manifest
  local response
  response=$(curl -sf -X POST "$url/mcp" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')

  local tool_count
  tool_count=$(echo "$response" | jq '.result.tools | length')
  echo "  Found $tool_count tools"

  # Extract MCP server prefixes for description
  local prefixes
  prefixes=$(echo "$response" | jq -r '.result.tools[].name' | cut -d- -f1 | sort -u | paste -sd', ')

  # Build the agent file
  local outfile="$AGENTS_DIR/${name}-agent.md"
  {
    # Frontmatter
    cat <<FRONTMATTER
---
name: ${name}-agent
description: Handles ${prefixes} operations via Bifrost gateway
tools: Bash
---

You are a tool-calling agent. You execute operations by calling MCP tools through the Bifrost gateway via curl.

## Gateway

- URL: \$BIFROST_${name^^}_URL (from environment, currently: $url)
- Transport: $transport

## Available Tools

FRONTMATTER

    # Generate tool entries
    echo "$response" | jq -r '.result.tools[] | @base64' | while read -r tool_b64; do
      local tool_name tool_desc tool_schema required_fields optional_fields
      tool_name=$(echo "$tool_b64" | base64 -d | jq -r '.name')
      tool_desc=$(echo "$tool_b64" | base64 -d | jq -r '.description')
      tool_schema=$(echo "$tool_b64" | base64 -d | jq '.inputSchema')
      required_fields=$(echo "$tool_schema" | jq -r '(.required // []) | join(", ")')
      optional_fields=$(echo "$tool_schema" | jq -r '[.properties | to_entries[] | select(.key as $k | ('"$(echo "$tool_schema" | jq -c '.required // []')"' | index($k)) == null) | .key] | join(", ")')

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

    # Invocation pattern
    if [ "$transport" = "stateless" ]; then
      cat <<'INVOKE'
## Invocation Pattern

To call a tool, use this curl pattern via Bash:

```bash
RESULT=$(curl -sf -X POST "$BIFROST_DEV_URL/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"TOOL_NAME","arguments":{...}}}')
echo "$RESULT" | jq -r '.result.content[0].text // .error.message'
```

Replace `TOOL_NAME` with the tool name from the manifest above. Replace `{...}` with a JSON object matching the tool's schema.

INVOKE
    elif [ "$transport" = "stateful" ]; then
      cat <<'INVOKE'
## Invocation Pattern (Stateful)

### Session initialization (run once at start)

```bash
INIT=$(curl -sf -X POST "$BIFROST_DESIGN_URL/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"subagent"}}}')
SESSION_ID=$(echo "$INIT" | jq -r '.result.sessionId')
echo "Session: $SESSION_ID"

curl -sf -X POST "$BIFROST_DESIGN_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"notifications/initialized"}'
```

### Tool calls (use session ID from initialization)

```bash
RESULT=$(curl -sf -X POST "$BIFROST_DESIGN_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"TOOL_NAME","arguments":{...}}}')
echo "$RESULT" | jq -r '.result.content[0].text // .error.message'
```

Read the session ID from the initialization output and pass it as a literal string in the `Mcp-Session-Id` header on every subsequent call.

INVOKE
    fi

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

# Main
for entry in "${GATEWAYS[@]}"; do
  IFS='|' read -r name url_env transport <<< "$entry"
  url="${!url_env:-}"
  if [ -z "$url" ]; then
    echo "SKIP: $name — \$$url_env not set" >&2
    continue
  fi
  generate_agent "$name" "$url" "$transport"
done

echo "Done."
