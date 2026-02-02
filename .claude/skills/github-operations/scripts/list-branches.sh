#!/bin/bash
# List branches in the repository

set -e

# Arguments
FILTER="${1:-}"
LIMIT="${2:-30}"

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    exit 1
fi

# Get repository owner and name from git remote
REPO_URL=$(git config --get remote.origin.url)
if [[ "$REPO_URL" =~ github\.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
    OWNER="${BASH_REMATCH[1]}"
    REPO="${BASH_REMATCH[2]}"
else
    echo "Error: Could not parse repository from remote URL: $REPO_URL" >&2
    exit 1
fi

# List branches via GitHub API
if [ -n "$FILTER" ]; then
    # Filter branches by pattern (e.g., "feature/TT-" to find all feature branches)
    gh api "repos/$OWNER/$REPO/branches?per_page=$LIMIT" | jq --arg filter "$FILTER" '[.[] | select(.name | contains($filter))]'
else
    gh api "repos/$OWNER/$REPO/branches?per_page=$LIMIT" | jq '[.[] | {name: .name, protected: .protected}]'
fi
