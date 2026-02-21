#!/bin/bash
# Add a comment to a GitHub pull request

set -e

# Arguments
PR_NUMBER="${1:-}"
COMMENT_BODY="${2:-}"

# Check required arguments
if [ -z "$PR_NUMBER" ]; then
    echo "Error: PR number is required" >&2
    echo "Usage: add-pr-comment.sh <pr-number> <comment-body>" >&2
    echo "Example: add-pr-comment.sh 45 'LGTM! Ready to merge.'" >&2
    exit 1
fi

if [ -z "$COMMENT_BODY" ]; then
    echo "Error: Comment body is required" >&2
    echo "Usage: add-pr-comment.sh <pr-number> <comment-body>" >&2
    exit 1
fi

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    exit 1
fi

# Add comment to PR
gh pr comment "$PR_NUMBER" --body "$COMMENT_BODY"

echo "Comment added to PR #$PR_NUMBER" >&2
