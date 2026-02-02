#!/bin/bash
# Get GitHub pull request details using gh CLI

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

# Get PR details
gh pr view "$PR_NUMBER" \
    --json number,title,body,state,headRefName,baseRefName,author,createdAt,updatedAt,mergeable,reviews,statusCheckRollup \
    --jq '.'
