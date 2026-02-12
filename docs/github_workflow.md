# GitHub Workflow — Delegation Guide

This document contains detailed examples and procedures for GitHub operations.
All GitHub operations MUST be delegated to the `github-workflow` agent via the Task tool.

See [CLAUDE.md](../CLAUDE.md) for the mandatory rules (kept inline there for agent visibility).

---

## Why Delegation Matters

The github-workflow agent is the **mandatory gatekeeper** for all GitHub operations. It enforces:

- **PR title format** (TT-XXX: Description)
- **PR body structure** (Summary, Related Jira Issue, Acceptance Criteria, Evidence, Test Evidence, Changes Made)
- **Branch naming conventions** (type/TT-XXX-description)
- **Commit message format** (TT-XXX: Description)
- **Functional evidence requirements** (mandatory for each AC)
- **Quality gates** (tests, type checking, linting)
- **Immediate branch push** after creation to trigger Jira automation

---

## Operations That Require Delegation

**ALWAYS use github-workflow agent for:**
- Creating pull requests
- Getting PR status and details
- Listing pull requests
- Viewing PR file changes
- Creating and pushing branches (CRITICAL: must push immediately after creation)
- Repository operations (commits, git operations)

**When to use:**
- Creating, listing, or viewing pull requests
- Any gh CLI operations
- Modifying files in `.claude/skills/github-operations/`
- Repository operations (branches, commits, tags)
- PR reviews, comments, status checks

---

## Correct Usage Patterns

### Creating a PR

```python
Task(
    subagent_type="github-workflow",
    description="Create PR for feature",
    prompt="""
    Create a pull request for the completed work:

    Branch: feature/TT-XXX-description
    Base: main
    Title: TT-XXX: Brief description

    Summary: [what was done]
    Changes: [list of changes]
    Evidence: [functional evidence for each AC from Jira ticket]
    """
)
```

### Creating and pushing a branch

```python
# Agent will create branch and IMMEDIATELY push to trigger Jira automation
Task(
    subagent_type="github-workflow",
    description="Create and push feature branch",
    prompt="Create branch feature/TT-XXX-add-feature and push immediately to remote"
)
```

### Getting PR status

```python
Task(
    subagent_type="github-workflow",
    description="Check PR status",
    prompt="Get status for PR #45 - are checks passing and is it ready to merge?"
)
```

---

## Incorrect Usage (DO NOT DO THIS)

```python
# NEVER DO THIS - These are BLOCKED:
Skill(command="github-operations")              # Will fail with permission error
Bash("gh pr create ...")                        # Blocked
Edit(".claude/skills/github-operations/...")    # Blocked - use agent
bash .claude/skills/github-operations/scripts/create-pr.sh "..." "..." "main" "..."
```

```python
# NEVER DO THIS - Jira automation won't trigger
git checkout -b feature/TT-XXX-description
# ... then work on it later without pushing
```

---

## Autonomous PR Creation Flow

When all ACs pass and code is pushed, create the PR immediately — do NOT ask permission.

```
Branch created       → Jira: In Progress
Code pushed + ACs pass → Create PR → Jira: In Review
PR merged (human)    → Jira: Done
```

---

## Branch Push Requirement

All new branches MUST be pushed to remote **immediately** after creation.

**Why:** Triggers Jira automation (To Do → In Progress) and signals work has started.

**The github-workflow agent automatically enforces:**

1. Update main branch
2. Create feature branch
3. **IMMEDIATELY push to remote** (even if empty)
4. Then proceed with work

---

## Branch Naming Conventions

- Format: `type/TT-XXX-description`
- Types: `feature/`, `fix/`, `refactor/`, `docs/`, `chore/`
- MUST include Jira ticket (TT-XXX) in branch name — enforced by agent
- NEVER work on `main` branch — github-workflow agent will REJECT operations
