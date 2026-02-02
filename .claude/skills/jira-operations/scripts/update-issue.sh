#!/bin/bash
# Update a Jira issue

set -e

# Arguments
ISSUE_KEY="$1"
FIELD="$2"
VALUE="$3"

# Validation
if [ -z "$ISSUE_KEY" ] || [ -z "$FIELD" ] || [ -z "$VALUE" ]; then
    echo "Error: Missing required arguments" >&2
    echo "Usage: $0 <issue-key> <field> <value>" >&2
    echo "Supported fields: summary, description, priority, parent" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  Update summary: $0 TT-122 summary 'New summary'" >&2
    echo "  Link to epic: $0 TT-122 parent TT-89" >&2
    echo "  Link to parent task: $0 TT-125 parent TT-122" >&2
    exit 1
fi

# Check environment variables
if [ -z "$ATLASSIAN_SITE_NAME" ] || [ -z "$ATLASSIAN_USER_EMAIL" ] || [ -z "$ATLASSIAN_API_TOKEN" ]; then
    echo "Error: Jira environment variables not set" >&2
    exit 1
fi

# Build JSON payload based on field type
case "$FIELD" in
    summary|description)
        PAYLOAD=$(jq -n --arg field "$FIELD" --arg value "$VALUE" '{fields: {($field): $value}}')
        ;;
    priority)
        PAYLOAD=$(jq -n --arg value "$VALUE" '{fields: {priority: {name: $value}}}')
        ;;
    parent)
        PAYLOAD=$(jq -n --arg value "$VALUE" '{fields: {parent: {key: $value}}}')
        ;;
    *)
        echo "Error: Unsupported field: $FIELD" >&2
        echo "Supported fields: summary, description, priority, parent" >&2
        exit 1
        ;;
esac

# Update issue
curl -s -X PUT \
    -H "Content-Type: application/json" \
    -u "${ATLASSIAN_USER_EMAIL}:${ATLASSIAN_API_TOKEN}" \
    -d "$PAYLOAD" \
    "${ATLASSIAN_SITE_NAME}/rest/api/2/issue/${ISSUE_KEY}"

# Return success (PUT returns no content on success)
echo '{"success": true, "issue": "'$ISSUE_KEY'", "field": "'$FIELD'"}'
