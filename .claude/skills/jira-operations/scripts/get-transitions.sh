#!/bin/bash
# Get available transitions for a Jira issue

set -e

# Arguments
ISSUE_KEY="$1"

# Validation
if [ -z "$ISSUE_KEY" ]; then
    echo "Error: Missing issue key" >&2
    echo "Usage: $0 <issue-key>" >&2
    exit 1
fi

# Check environment variables
if [ -z "$ATLASSIAN_SITE_NAME" ] || [ -z "$ATLASSIAN_USER_EMAIL" ] || [ -z "$ATLASSIAN_API_TOKEN" ]; then
    echo "Error: Jira environment variables not set" >&2
    exit 1
fi

# Get transitions
curl -s -X GET \
    -H "Content-Type: application/json" \
    -u "${ATLASSIAN_USER_EMAIL}:${ATLASSIAN_API_TOKEN}" \
    "${ATLASSIAN_SITE_NAME}/rest/api/2/issue/${ISSUE_KEY}/transitions" \
    | jq '.transitions[] | {id: .id, name: .name, to: .to.name}'
