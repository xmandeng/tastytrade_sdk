#!/bin/bash
# Get available issue types for a Jira project

set -e

# Arguments
PROJECT_KEY="${1:-QUE}"

# Validation
if [ -z "$PROJECT_KEY" ]; then
    echo "Error: Missing project key" >&2
    echo "Usage: $0 [project-key]" >&2
    exit 1
fi

# Check environment variables
if [ -z "$ATLASSIAN_SITE_NAME" ] || [ -z "$ATLASSIAN_USER_EMAIL" ] || [ -z "$ATLASSIAN_API_TOKEN" ]; then
    echo "Error: Jira environment variables not set" >&2
    exit 1
fi

# Get issue types by searching existing issues and extracting unique types
# This approach works reliably across API versions
curl -s -X GET \
    -H "Content-Type: application/json" \
    -u "${ATLASSIAN_USER_EMAIL}:${ATLASSIAN_API_TOKEN}" \
    "${ATLASSIAN_SITE_NAME}/rest/api/3/search/jql?jql=project%20%3D%20${PROJECT_KEY}&fields=issuetype&maxResults=100" \
    | jq -r '.issues[].fields.issuetype | {id: .id, name: .name, subtask: .subtask, hierarchyLevel: .hierarchyLevel}' \
    | jq -s 'unique_by(.id) | sort_by(.hierarchyLevel) | reverse'
