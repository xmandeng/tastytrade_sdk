#!/bin/bash
###
# SubagentStop Hook - LangSmith Tracing for Subagents
# Adapts SubagentStop input and delegates to stop_hook.sh
# so subagent token usage and actions are traced to LangSmith.
###

set -e

# Read hook input
HOOK_INPUT=$(cat)

# Early exit if stop_hook is already active (prevent loops)
if echo "$HOOK_INPUT" | jq -e '.stop_hook_active == true' > /dev/null 2>&1; then
    exit 0
fi

# Early exit if tracing disabled
if [ "$(echo "$TRACE_TO_LANGSMITH" | tr '[:upper:]' '[:lower:]')" != "true" ]; then
    exit 0
fi

# Extract subagent-specific fields
AGENT_ID=$(echo "$HOOK_INPUT" | jq -r '.agent_id // ""')
AGENT_TYPE=$(echo "$HOOK_INPUT" | jq -r '.agent_type // ""')
AGENT_TRANSCRIPT=$(echo "$HOOK_INPUT" | jq -r '.agent_transcript_path // ""')
PARENT_SESSION=$(echo "$HOOK_INPUT" | jq -r '.session_id // ""')

# Validate
if [ -z "$AGENT_TRANSCRIPT" ] || [ -z "$AGENT_ID" ]; then
    exit 0
fi

# Resolve ~ in path
AGENT_TRANSCRIPT=$(echo "$AGENT_TRANSCRIPT" | sed "s|^~|$HOME|")

if [ ! -f "$AGENT_TRANSCRIPT" ]; then
    exit 0
fi

# Build run name: {project}({agent_type}) for visual distinction across projects
# Preserve the existing CC_LANGSMITH_RUN_NAME (project name from .env) as base
BASE_NAME="${CC_LANGSMITH_RUN_NAME:-}"
if [ -z "$BASE_NAME" ]; then
    # Fall back to git repo name
    if command -v git &> /dev/null && git rev-parse --git-dir &> /dev/null 2>&1; then
        GIT_REMOTE=$(git config --get remote.origin.url 2>/dev/null || echo "")
        if [ -n "$GIT_REMOTE" ]; then
            BASE_NAME=$(echo "$GIT_REMOTE" | sed -e 's/.*[:/]\([^/]*\/[^/]*\)\.git$/\1/' -e 's/.*[:/]\([^/]*\/[^/]*\)$/\1/' | sed 's/.*\///')
        fi
    fi
    BASE_NAME="${BASE_NAME:-Claude Code}"
fi
export CC_LANGSMITH_RUN_NAME="${BASE_NAME}(${AGENT_TYPE})"

# Pass parent session for trace linking
export CC_LANGSMITH_PARENT_SESSION="$PARENT_SESSION"
export CC_LANGSMITH_EXTRA_TAGS="subagent,$AGENT_TYPE"

# Transform hook input to look like a Stop hook input:
# - Replace transcript_path with agent_transcript_path
# - Use "subagent-{agent_id}" as session_id for state tracking
MODIFIED_INPUT=$(echo "$HOOK_INPUT" | jq \
    --arg tp "$AGENT_TRANSCRIPT" \
    '.transcript_path = $tp | .session_id = ("subagent-" + .agent_id) | .stop_hook_active = false')

# Delegate to the existing stop_hook.sh (resolve path relative to this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "$MODIFIED_INPUT" | bash -l "$SCRIPT_DIR/stop_hook.sh"
