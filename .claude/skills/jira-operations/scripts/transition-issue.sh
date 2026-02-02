#!/bin/bash
# Transition a Jira issue to a new status

set -e

# Arguments
ISSUE_KEY="$1"
TRANSITION_ID="$2"

# Validation
if [ -z "$ISSUE_KEY" ] || [ -z "$TRANSITION_ID" ]; then
    echo "Error: Missing required arguments" >&2
    echo "Usage: $0 <issue-key> <transition-id>" >&2
    echo "Get transition IDs with: get-transitions.sh <issue-key>" >&2
    exit 1
fi

# Check environment variables
if [ -z "$ATLASSIAN_SITE_NAME" ] || [ -z "$ATLASSIAN_USER_EMAIL" ] || [ -z "$ATLASSIAN_API_TOKEN" ]; then
    echo "Error: Jira environment variables not set" >&2
    exit 1
fi

# Build JSON payload
PAYLOAD=$(jq -n --arg id "$TRANSITION_ID" '{transition: {id: $id}}')

# Transition issue
curl -s -X POST \
    -H "Content-Type: application/json" \
    -u "${ATLASSIAN_USER_EMAIL}:${ATLASSIAN_API_TOKEN}" \
    -d "$PAYLOAD" \
    "${ATLASSIAN_SITE_NAME}/rest/api/2/issue/${ISSUE_KEY}/transitions"

# Return success (POST returns no content on success)
echo '{"success": true, "issue": "'$ISSUE_KEY'", "transition_id": "'$TRANSITION_ID'"}'
