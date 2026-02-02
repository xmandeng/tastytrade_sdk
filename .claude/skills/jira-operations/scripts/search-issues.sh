#!/bin/bash
# Search Jira issues using JQL

set -e

# Arguments
JQL="$1"
FIELDS="${2:-summary,status,issuetype,created,priority}"
LIMIT="${3:-50}"

# Validation
if [ -z "$JQL" ]; then
    echo "Error: Missing JQL query" >&2
    echo "Usage: $0 <jql> [fields] [limit]" >&2
    exit 1
fi

# Check environment variables
if [ -z "$ATLASSIAN_SITE_NAME" ] || [ -z "$ATLASSIAN_USER_EMAIL" ] || [ -z "$ATLASSIAN_API_TOKEN" ]; then
    echo "Error: Jira environment variables not set" >&2
    echo "Required: ATLASSIAN_SITE_NAME, ATLASSIAN_USER_EMAIL, ATLASSIAN_API_TOKEN" >&2
    exit 1
fi

# Build API request (using API v3/search/jql endpoint)
curl -s -X GET \
    -H "Content-Type: application/json" \
    -u "${ATLASSIAN_USER_EMAIL}:${ATLASSIAN_API_TOKEN}" \
    "${ATLASSIAN_SITE_NAME}/rest/api/3/search/jql?jql=$(echo "$JQL" | jq -sRr @uri)&fields=${FIELDS}&maxResults=${LIMIT}" \
    | jq '.'
