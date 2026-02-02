#!/bin/bash
# Re-run a failed GitHub Actions workflow

set -e

# Arguments
RUN_ID="${1:-}"
FAILED_ONLY="${2:-}"

# Check required arguments
if [ -z "$RUN_ID" ]; then
    echo "Error: Workflow run ID is required" >&2
    echo "Usage: rerun-workflow.sh <run-id> [--failed-only]" >&2
    echo "Example: rerun-workflow.sh 12345678" >&2
    echo "Example: rerun-workflow.sh 12345678 --failed-only" >&2
    exit 1
fi

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed" >&2
    exit 1
fi

# Re-run the workflow
if [ "$FAILED_ONLY" = "--failed-only" ]; then
    echo "Re-running failed jobs for workflow run $RUN_ID..." >&2
    gh run rerun "$RUN_ID" --failed
else
    echo "Re-running all jobs for workflow run $RUN_ID..." >&2
    gh run rerun "$RUN_ID"
fi

echo "Workflow re-run initiated" >&2

# Get updated status
gh run view "$RUN_ID" --json workflowName,status,url | jq '.'
