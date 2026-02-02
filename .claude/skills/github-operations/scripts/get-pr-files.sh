#!/bin/bash
# Get files changed in a GitHub pull request using gh CLI

set -e

# Arguments
PR_NUMBER="$1"

# Validation
if [ -z "$PR_NUMBER" ]; then
    echo "Error: Missing PR number" >&2
    echo "Usage: $0 <pr-number>" >&2
    exit 1
fi

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    exit 1
fi

# Get changed files
gh pr view "$PR_NUMBER" \
    --json files \
    --jq '.files[] | {path: .path, additions: .additions, deletions: .deletions, changes: .changes}'
