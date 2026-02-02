#!/bin/bash
# Create a GitHub pull request using gh CLI

set -e

# Arguments
TITLE="$1"
BODY="$2"
BASE="${3:-main}"

# Validation
if [ -z "$TITLE" ]; then
    echo "Error: Missing required arguments" >&2
    echo "Usage: $0 <title> <body> [base]" >&2
    echo "" >&2
    echo "Creates PR from current branch to base branch" >&2
    echo "Example: $0 'PR title' 'PR body' main" >&2
    exit 1
fi

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    echo "Install: https://cli.github.com/" >&2
    exit 1
fi

# Create PR (gh auto-detects head from current branch)
if [ -n "$BODY" ]; then
    gh pr create \
        --title "$TITLE" \
        --base "$BASE" \
        --body "$BODY"
else
    gh pr create \
        --title "$TITLE" \
        --base "$BASE" \
        --fill
fi
