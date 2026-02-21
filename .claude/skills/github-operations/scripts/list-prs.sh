#!/bin/bash
# List GitHub pull requests using gh CLI

set -e

# Arguments
STATE="${1:-open}"
BASE="$2"

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    exit 1
fi

# Build command
CMD="gh pr list --state $STATE --json number,title,headRefName,baseRefName,state,updatedAt,author"

# Add base branch filter if specified
if [ -n "$BASE" ]; then
    CMD="$CMD --base $BASE"
fi

# Execute and format
eval "$CMD" | jq '.'
