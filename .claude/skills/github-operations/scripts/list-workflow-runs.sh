#!/bin/bash
# List GitHub Actions workflow runs using gh CLI

set -e

# Arguments
WORKFLOW="${1:-}"
LIMIT="${2:-10}"
BRANCH="${3:-}"

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    exit 1
fi

# Build command
CMD="gh run list --limit $LIMIT --json workflowName,event,status,conclusion,headBranch,createdAt,databaseId"

# Add workflow filter if specified
if [ -n "$WORKFLOW" ]; then
    CMD="$CMD --workflow=$WORKFLOW"
fi

# Add branch filter if specified
if [ -n "$BRANCH" ]; then
    CMD="$CMD --branch=$BRANCH"
fi

# Execute and format
eval "$CMD" | jq '.'
