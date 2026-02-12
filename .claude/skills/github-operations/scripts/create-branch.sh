#!/bin/bash
# Create a branch on remote via GitHub API and set up a worktree for parallel work

set -e

# Arguments
BRANCH_NAME="${1:-}"
BASE_REF="${2:-main}"
WORKTREE_BASE="${3:-/tmp/worktrees}"

# Check required arguments
if [ -z "$BRANCH_NAME" ]; then
    echo "Error: Branch name is required" >&2
    echo "Usage: create-branch.sh <branch-name> [base-ref] [worktree-base]" >&2
    echo "Example: create-branch.sh feature/TT-123-add-feature main" >&2
    exit 1
fi

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

# Extract ticket ID for worktree directory name (e.g., TT-123 from feature/TT-123-description)
TICKET_ID=$(echo "$BRANCH_NAME" | grep -oE '[A-Z]+-[0-9]+' | head -1)
if [ -z "$TICKET_ID" ]; then
    TICKET_ID=$(echo "$BRANCH_NAME" | tr '/' '-')
fi
WORKTREE_PATH="$WORKTREE_BASE/$TICKET_ID"

# Fetch the latest state of the base reference from remote
echo "Fetching latest '$BASE_REF' from remote..." >&2
git fetch origin "$BASE_REF" 2>/dev/null || {
    echo "Error: Could not fetch base reference: $BASE_REF" >&2
    exit 1
}

# Get the SHA from the fetched remote ref (ensures we use latest, not stale local state)
BASE_SHA=$(git rev-parse "origin/$BASE_REF" 2>/dev/null)
if [ -z "$BASE_SHA" ]; then
    echo "Error: Could not resolve base reference: origin/$BASE_REF" >&2
    exit 1
fi

echo "Creating branch '$BRANCH_NAME' from '$BASE_REF'..." >&2
echo "Repository: $OWNER/$REPO" >&2

# Create branch on remote via GitHub API (triggers 'create' event for Jira)
RESPONSE=$(gh api "repos/$OWNER/$REPO/git/refs" \
    -f ref="refs/heads/$BRANCH_NAME" \
    -f sha="$BASE_SHA" 2>&1)

if [ $? -ne 0 ]; then
    echo "Error creating branch: $RESPONSE" >&2
    exit 1
fi

echo "Branch created on remote (Jira automation triggered)" >&2

# Fetch the new branch
git fetch origin "$BRANCH_NAME" >&2

# Create worktree directory if needed
mkdir -p "$WORKTREE_BASE"

# Remove existing worktree if present
if [ -d "$WORKTREE_PATH" ]; then
    echo "Removing existing worktree at $WORKTREE_PATH..." >&2
    git worktree remove "$WORKTREE_PATH" --force 2>/dev/null || rm -rf "$WORKTREE_PATH"
fi

# Create worktree
git worktree add "$WORKTREE_PATH" "origin/$BRANCH_NAME" >&2

# Symlink .env so worktree has access to the same configuration
MAIN_WORKSPACE=$(git rev-parse --show-toplevel)
if [ -f "$MAIN_WORKSPACE/.env" ]; then
    ln -sf "$MAIN_WORKSPACE/.env" "$WORKTREE_PATH/.env"
    echo "Symlinked .env into worktree" >&2
fi

# Output result as JSON for easy parsing
echo "{\"branch\": \"$BRANCH_NAME\", \"worktree\": \"$WORKTREE_PATH\", \"ticket\": \"$TICKET_ID\"}"
