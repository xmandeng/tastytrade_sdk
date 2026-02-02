---
name: github-operations
description: GitHub pull request and repository operations using gh CLI for the quber_excel repository (xmandeng/tastytrade_sdk). Use when creating PRs, listing PRs, getting PR status, viewing PR files, or performing git operations. Automatically detects repository from git remote.
allowed-tools: Bash, Read, Grep, Glob
---

# GitHub Operations Skill

This Skill provides GitHub pull request and repository management capabilities using the GitHub CLI (`gh`) tool.

## Prerequisites

- GitHub CLI (`gh`) must be installed and authenticated
- Repository: `xmandeng/tastytrade_sdk` (auto-detected from git remote)
- Environment: `GITHUB_PERSONAL_ACCESS_TOKEN` must be set

## Available Operations

### 1. Create Pull Request

**Script**: `scripts/create-pr.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/create-pr.sh \
  "title" \
  "PR body content" \
  "base-branch"
```

**Arguments**:
- `title`: PR title (follows TT-XXX: format)
- `body`: PR description (markdown format)
- `base`: Target branch (optional, defaults to "main")

**Note**: Head branch is auto-detected from current git branch by gh pr create.

**Example**:
```bash
bash .claude/skills/github-operations/scripts/create-pr.sh \
  "TT-123: Add CLI markdown converter" \
  "## Summary
Add CLI for markdown conversion

## Changes Made
- Implement convert command
- Add tests" \
  "main"
```

### 2. List Pull Requests

**Script**: `scripts/list-prs.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/list-prs.sh [state] [base]
```

**Arguments**:
- `state`: PR state (open, closed, merged, all) - default: open
- `base`: Base branch filter - default: all branches

**Example**:
```bash
# List open PRs
bash .claude/skills/github-operations/scripts/list-prs.sh open main

# List all PRs
bash .claude/skills/github-operations/scripts/list-prs.sh all
```

### 3. Get Pull Request Details

**Script**: `scripts/get-pr.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/get-pr.sh <pr-number>
```

**Arguments**:
- `pr-number`: Pull request number

**Example**:
```bash
bash .claude/skills/github-operations/scripts/get-pr.sh 45
```

### 4. Get Pull Request Files

**Script**: `scripts/get-pr-files.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/get-pr-files.sh <pr-number>
```

**Arguments**:
- `pr-number`: Pull request number

**Example**:
```bash
bash .claude/skills/github-operations/scripts/get-pr-files.sh 45
```

### 5. List Workflow Runs

**Script**: `scripts/list-workflow-runs.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/list-workflow-runs.sh [workflow] [limit] [branch]
```

**Arguments**:
- `workflow`: Workflow filename (e.g., `jira-transition.yml`) - optional
- `limit`: Number of runs to return - default: 10
- `branch`: Filter by branch name - optional

**Example**:
```bash
# List recent runs for jira-transition workflow
bash .claude/skills/github-operations/scripts/list-workflow-runs.sh jira-transition.yml 5

# List runs for a specific branch
bash .claude/skills/github-operations/scripts/list-workflow-runs.sh jira-transition.yml 5 feature/TT-6-cli-scaffold

# List all recent workflow runs
bash .claude/skills/github-operations/scripts/list-workflow-runs.sh "" 10
```

### 6. Create Branch + Worktree

**Script**: `scripts/create-branch.sh`

Creates branch via GitHub API (triggers Jira automation) and sets up a worktree for parallel work.

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/create-branch.sh <branch-name> [base-ref] [worktree-base]
```

**Arguments**:
- `branch-name`: Branch name (e.g., `feature/TT-123-add-feature`)
- `base-ref`: Base branch - default: `main`
- `worktree-base`: Worktree directory - default: `/tmp/worktrees`

**Output** (JSON):
```json
{"branch": "feature/TT-123-desc", "worktree": "/tmp/worktrees/TT-123", "ticket": "TT-123"}
```

**Example**:
```bash
bash .claude/skills/github-operations/scripts/create-branch.sh feature/TT-123-add-feature main
# Work in: /tmp/worktrees/TT-123
```

### 7. Get Workflow Run Details

**Script**: `scripts/get-workflow-run.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/get-workflow-run.sh <run-id>
```

**Arguments**:
- `run-id`: The workflow run ID (from `list-workflow-runs.sh` output)

**Example**:
```bash
bash .claude/skills/github-operations/scripts/get-workflow-run.sh 12345678
```

### 8. Add PR Comment

**Script**: `scripts/add-pr-comment.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/add-pr-comment.sh <pr-number> <comment-body>
```

**Arguments**:
- `pr-number`: Pull request number
- `comment-body`: Comment text (supports markdown)

**Example**:
```bash
bash .claude/skills/github-operations/scripts/add-pr-comment.sh 45 "LGTM! Ready for review."
```

### 9. Delete Branch

**Script**: `scripts/delete-branch.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/delete-branch.sh <branch-name> [--force]
```

**Arguments**:
- `branch-name`: Name of the branch to delete
- `--force`: Also delete local branch (optional)

**Safety**: Protected branches (`main`, `master`, `develop`, `production`) cannot be deleted.

**Example**:
```bash
# Delete remote branch only
bash .claude/skills/github-operations/scripts/delete-branch.sh feature/TT-123-add-feature

# Delete both remote and local
bash .claude/skills/github-operations/scripts/delete-branch.sh feature/TT-123-add-feature --force
```

### 10. List Branches

**Script**: `scripts/list-branches.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/list-branches.sh [filter] [limit]
```

**Arguments**:
- `filter`: Filter branches containing this string - optional
- `limit`: Maximum number of branches to return - default: 30

**Example**:
```bash
# List all branches
bash .claude/skills/github-operations/scripts/list-branches.sh

# List feature branches
bash .claude/skills/github-operations/scripts/list-branches.sh "feature/"

# List TT-6 related branches
bash .claude/skills/github-operations/scripts/list-branches.sh "TT-6"
```

### 11. Re-run Workflow

**Script**: `scripts/rerun-workflow.sh`

**Usage**:
```bash
bash .claude/skills/github-operations/scripts/rerun-workflow.sh <run-id> [--failed-only]
```

**Arguments**:
- `run-id`: The workflow run ID to re-run
- `--failed-only`: Only re-run failed jobs (optional)

**Example**:
```bash
# Re-run all jobs
bash .claude/skills/github-operations/scripts/rerun-workflow.sh 12345678

# Re-run only failed jobs
bash .claude/skills/github-operations/scripts/rerun-workflow.sh 12345678 --failed-only
```

## PR Conventions for quber_excel

**IMPORTANT**: All PR standards are defined in `docs/GITHUB_WORKFLOW_SPEC.md`. This Skill follows those specifications.

### Quick Reference

**Title Format**: `TT-XXX: Brief description of changes`
- Example: `TT-149: Refactor github-workflow agent to reference GITHUB_WORKFLOW_SPEC.md`

**Branch Naming**: `<type>/TT-XXX-brief-description`
- Example: `feature/TT-149-refactor-github-agent-specs`
- Example: `bugfix/TT-131-fix-jira-exit-error`

**PR Body**: Must include Summary, Related Jira Issue, Acceptance Criteria with Functional Evidence, Test Evidence, Changes Made

See `docs/GITHUB_WORKFLOW_SPEC.md` for complete PR standards, functional evidence requirements, and quality gates.

## Error Handling

All scripts return:
- **Exit code 0**: Success
- **Exit code 1**: Error (check stderr for details)

## Integration with Agents

This Skill is designed for use by the `github-workflow` agent. When the agent needs to perform GitHub operations:

1. Agent determines operation needed
2. Agent calls appropriate script via Bash tool
3. Script executes using `gh` CLI
4. Results returned to agent
5. Agent formats response for user

## Repository Auto-Detection

The GitHub CLI (`gh`) automatically detects the repository from `git config --get remote.origin.url`. Scripts do not need to specify `owner` and `repo` parameters.

To verify repository:
```bash
git remote -v
```

Should show: `origin  git@github.com:xmandeng/tastytrade_sdk.git`
