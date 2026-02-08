#!/bin/bash
# Edit a GitHub pull request using gh CLI

set -e

# Arguments
PR_NUMBER="$1"
BODY="$2"
TITLE="$3"

# Validation
if [ -z "$PR_NUMBER" ]; then
    echo "Error: Missing required arguments" >&2
    echo "Usage: $0 <pr-number> <body> [title]" >&2
    echo "" >&2
    echo "Edit PR body (and optionally title)" >&2
    echo "Example: $0 84 'New PR body' 'Optional new title'" >&2
    exit 1
fi

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    echo "Install: https://cli.github.com/" >&2
    exit 1
fi

# Build edit command
if [ -n "$TITLE" ]; then
    gh pr edit "$PR_NUMBER" --body "$BODY" --title "$TITLE"
else
    gh pr edit "$PR_NUMBER" --body "$BODY"
fi

echo "PR #$PR_NUMBER updated successfully"
