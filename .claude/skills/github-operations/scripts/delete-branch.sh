#!/bin/bash
# Delete a branch from remote repository

set -e

# Arguments
BRANCH_NAME="${1:-}"
FORCE="${2:-}"

# Check required arguments
if [ -z "$BRANCH_NAME" ]; then
    echo "Error: Branch name is required" >&2
    echo "Usage: delete-branch.sh <branch-name> [--force]" >&2
    echo "Example: delete-branch.sh feature/TT-123-add-feature" >&2
    exit 1
fi

# Safety check - prevent deletion of protected branches
PROTECTED_BRANCHES=("main" "master" "develop" "production")
for protected in "${PROTECTED_BRANCHES[@]}"; do
    if [ "$BRANCH_NAME" = "$protected" ]; then
        echo "Error: Cannot delete protected branch: $BRANCH_NAME" >&2
        exit 1
    fi
done

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    exit 1
fi

# Check if branch exists on remote
if ! git ls-remote --exit-code --heads origin "$BRANCH_NAME" > /dev/null 2>&1; then
    echo "Error: Branch '$BRANCH_NAME' does not exist on remote" >&2
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

echo "Deleting branch '$BRANCH_NAME' from $OWNER/$REPO..." >&2

# Delete the branch via GitHub API
RESPONSE=$(gh api -X DELETE "repos/$OWNER/$REPO/git/refs/heads/$BRANCH_NAME" 2>&1)

if [ $? -eq 0 ]; then
    echo "Successfully deleted remote branch: $BRANCH_NAME" >&2

    # Also delete local branch if it exists
    if git show-ref --verify --quiet "refs/heads/$BRANCH_NAME"; then
        if [ "$FORCE" = "--force" ]; then
            git branch -D "$BRANCH_NAME" 2>/dev/null || true
            echo "Deleted local branch: $BRANCH_NAME" >&2
        else
            echo "Local branch still exists. Use 'git branch -d $BRANCH_NAME' to delete it." >&2
        fi
    fi

    echo '{"status": "deleted", "branch": "'"$BRANCH_NAME"'"}' | jq '.'
else
    echo "Error deleting branch: $RESPONSE" >&2
    exit 1
fi
