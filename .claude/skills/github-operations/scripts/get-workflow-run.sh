#!/bin/bash
# Get details of a specific GitHub Actions workflow run

set -e

# Arguments
RUN_ID="${1:-}"

# Check required arguments
if [ -z "$RUN_ID" ]; then
    echo "Error: Workflow run ID is required" >&2
    echo "Usage: get-workflow-run.sh <run-id>" >&2
    echo "Example: get-workflow-run.sh 12345678" >&2
    exit 1
fi

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    exit 1
fi

# Get workflow run details
gh run view "$RUN_ID" --json workflowName,event,status,conclusion,headBranch,createdAt,updatedAt,jobs,url | jq '.'
