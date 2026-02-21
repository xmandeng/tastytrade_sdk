#!/bin/bash
# Create a Jira issue (with optional parent for subtasks/epic linking)

set -e

# Arguments
SUMMARY="$1"
DESCRIPTION="$2"
ISSUE_TYPE="${3:-Task}"
PRIORITY="${4:-Medium}"
PROJECT_KEY="${5:-TT}"
PARENT_KEY="${6:-}"
LABELS="${7}"  # Labels parameter (optional)
# Default to project label if not provided or empty
if [ -z "$LABELS" ]; then
    LABELS="$JIRA_PROJECT_LABEL"
fi

# Validation
if [ -z "$SUMMARY" ] || [ -z "$DESCRIPTION" ]; then
    echo "Error: Missing required arguments" >&2
    echo "Usage: $0 <summary> <description> [issue-type] [priority] [project-key] [parent-key] [labels]" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  Create standalone task: $0 'Fix bug' 'Description' 'Task' 'High'" >&2
    echo "  Create subtask: $0 'Fix bug' 'Description' 'Subtask' 'High' 'TT' 'TT-122'" >&2
    echo "  Link to epic: $0 'New feature' 'Description' 'Task' 'High' 'TT' 'TT-89'" >&2
    echo "  With custom labels: $0 'Fix bug' 'Description' 'Task' 'High' 'TT' '' 'label1,label2'" >&2
    echo "" >&2
    echo "Note: Labels defaults to \$JIRA_PROJECT_LABEL if not specified" >&2
    exit 1
fi

# Check environment variables
if [ -z "$ATLASSIAN_SITE_NAME" ] || [ -z "$ATLASSIAN_USER_EMAIL" ] || [ -z "$ATLASSIAN_API_TOKEN" ]; then
    echo "Error: Jira environment variables not set" >&2
    exit 1
fi

# Convert comma-separated labels to JSON array
if [ -n "$LABELS" ]; then
    LABELS_ARRAY=$(echo "$LABELS" | jq -R 'split(",") | map(. | gsub("^\\s+|\\s+$";""))')
else
    LABELS_ARRAY="[]"
fi

# Build JSON payload with optional parent and labels
if [ -n "$PARENT_KEY" ]; then
    PAYLOAD=$(jq -n \
        --arg project "$PROJECT_KEY" \
        --arg summary "$SUMMARY" \
        --arg description "$DESCRIPTION" \
        --arg issuetype "$ISSUE_TYPE" \
        --arg priority "$PRIORITY" \
        --arg parent "$PARENT_KEY" \
        --argjson labels "$LABELS_ARRAY" \
        '{
            fields: {
                project: { key: $project },
                summary: $summary,
                description: $description,
                issuetype: { name: $issuetype },
                priority: { name: $priority },
                parent: { key: $parent },
                labels: $labels
            }
        }')
else
    PAYLOAD=$(jq -n \
        --arg project "$PROJECT_KEY" \
        --arg summary "$SUMMARY" \
        --arg description "$DESCRIPTION" \
        --arg issuetype "$ISSUE_TYPE" \
        --arg priority "$PRIORITY" \
        --argjson labels "$LABELS_ARRAY" \
        '{
            fields: {
                project: { key: $project },
                summary: $summary,
                description: $description,
                issuetype: { name: $issuetype },
                priority: { name: $priority },
                labels: $labels
            }
        }')
fi

# Create issue
curl -s -X POST \
    -H "Content-Type: application/json" \
    -u "${ATLASSIAN_USER_EMAIL}:${ATLASSIAN_API_TOKEN}" \
    -d "$PAYLOAD" \
    "${ATLASSIAN_SITE_NAME}/rest/api/2/issue" \
    | jq '.'
