#!/bin/bash
# Add a comment to a Jira issue

set -e

# Arguments
ISSUE_KEY="$1"
COMMENT="$2"

# Validation
if [ -z "$ISSUE_KEY" ] || [ -z "$COMMENT" ]; then
    echo "Error: Missing required arguments" >&2
    echo "Usage: $0 <issue-key> <comment>" >&2
    exit 1
fi

# Check environment variables
if [ -z "$ATLASSIAN_SITE_NAME" ] || [ -z "$ATLASSIAN_USER_EMAIL" ] || [ -z "$ATLASSIAN_API_TOKEN" ]; then
    echo "Error: Jira environment variables not set" >&2
    exit 1
fi

# Build JSON payload
PAYLOAD=$(jq -n --arg comment "$COMMENT" '{body: $comment}')

# Add comment
curl -s -X POST \
    -H "Content-Type: application/json" \
    -u "${ATLASSIAN_USER_EMAIL}:${ATLASSIAN_API_TOKEN}" \
    -d "$PAYLOAD" \
    "${ATLASSIAN_SITE_NAME}/rest/api/2/issue/${ISSUE_KEY}/comment" \
    | jq '.'
