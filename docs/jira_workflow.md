# Jira Workflow — Delegation Guide

This document contains detailed examples, templates, and procedures for Jira operations.
All Jira operations MUST be delegated to the `jira-workflow` agent via the Task tool.

See [CLAUDE.md](../CLAUDE.md) for the mandatory rules (kept inline there for agent visibility).

---

## Why Delegation Matters

The jira-workflow agent is the **mandatory gatekeeper** for all Jira operations. It enforces:

- **Intelligent type selection** (Story/Task/Bug/Sub-task based on request analysis)
- **Quality standards** (Test Evidence Requirements embedded in all templates)
- **Epic governance** (can link to Epics, cannot create Epics)
- **Validation rules** (ensures tickets meet project standards)
- **Type-agnostic workflow** (dispatcher processes any ticket type)

---

## Operations That Require Delegation

**ALWAYS use jira-workflow agent for:**
- Creating tickets (Story, Task, Bug, Sub-task — NOT Epic)
- Updating tickets (fields, descriptions, priorities)
- Linking tickets (to Epics, to parent issues)
- Searching tickets (JQL queries)
- Adding comments to tickets
- Getting ticket details
- Managing sprints (when applicable)

**When to use:**
- User mentions a Jira ticket (TT-XXX)
- User asks to "work on TT-XXX" or "start TT-XXX"
- Need to get issue details, update status, add comments
- Need to create new issues or search existing ones

---

## Correct Usage Patterns

### Creating a ticket

```python
Task(
    subagent_type="jira-workflow",
    description="Create Jira ticket for feature",
    prompt="""
    Create a ticket for the following work:

    Feature: Add WebSocket reconnection logic
    Context: Users need automatic reconnection when market data streams disconnect
    Priority: High

    Please create the appropriate ticket type (Story/Task/Bug) based on this request
    and link it to the relevant Epic if obvious from context.
    """
)
```

### Letting the agent determine type

```python
# Agent will analyze "fix bug" and create Bug ticket
Task(
    subagent_type="jira-workflow",
    description="Create ticket for bug fix",
    prompt="Create ticket: Fix message routing failure on malformed events"
)
```

### Searching tickets

```python
Task(
    subagent_type="jira-workflow",
    description="Find tickets in epic",
    prompt="Find all Stories in Market Data epic (TT-1) that are in To Do status"
)
```

---

## Incorrect Usage (DO NOT DO THIS)

```python
# NEVER DO THIS - These are BLOCKED:
Skill(command="jira-operations")  # Will fail with permission error
Bash("jira-cli ...")              # Blocked
bash .claude/skills/jira-operations/scripts/create-issue.sh "..." "..." "Story"
```

```python
# NEVER DO THIS - Epics are team-managed strategic tools
Task(
    subagent_type="jira-workflow",
    prompt="Create Epic for Q2 Roadmap"
)
# jira-workflow agent will correctly decline this request
```

---

## Type-Agnostic Approach

The jira-workflow agent uses **intelligent type selection**:
- Analyzes your request and keywords
- Automatically selects Story/Task/Bug/Sub-task
- Asks for clarification if ambiguous
- Refuses to create Epics (team governance)

**You don't need to specify the type** — just describe what needs to be done:

```python
"Add real-time quote streaming"       # → Story (user-facing feature)
"Refactor message router logic"       # → Task (technical work)
"Fix WebSocket connection drops"      # → Bug (defect)
"Create API endpoint under TT-50"     # → Sub-task (implementation piece)
```

---

## Verbatim Content Rule — Full Details

**The jira-workflow agent paraphrases by default. You MUST prevent this.**

When passing plans, code snippets, field lists, or implementation details, explicitly instruct it to use the content **verbatim**.

**Include this instruction in every prompt with detailed content:**

> Use the following content VERBATIM in the description. Do NOT paraphrase, summarize, or rewrite. Copy it exactly as provided.

### What must be passed verbatim (when available):

- Code snippets with file paths and line numbers
- Field lists, enum values, method signatures
- Test function names, factory function specs
- API response shapes
- Design rationale
- Acceptance criteria mappings

**Why:** The implementing agent has zero context from your conversation. Paraphrased summaries lose the exact details (field names, line numbers, code patterns) that make a ticket actionable.

---

## Status Transitions

Status transitions are handled by GitHub workflows, NOT manually:

- Branch created → Jira moves to "In Progress" (via `.github/workflows/jira-transition.yml`)
- PR opened → Jira moves to "In Review" (automated)
- PR merged → Jira moves to "Done" (automated)

jira-workflow agent has read-only status awareness. Do not manually transition tickets.

---

## Epic Governance

Epics are strategic planning tools managed by the team.

- Agent CAN link tickets to existing Epics
- Agent CANNOT create new Epics

If you need an Epic created, ask the team to create it manually in Jira, then use jira-workflow agent to link tickets to it.

---

## Implementation Completion Documentation

When you complete work on a Jira ticket, you MUST add a comprehensive implementation comment via the jira-workflow agent.

The comment MUST include:

### 1. Expected Behaviors (MOST IMPORTANT)

Describe changes from user/operational perspective using Before/After format:

```
Before: Status showed subscription creation time, not actual data flow
After: Status shows when data was last received (e.g., "8s ago" updating in real-time)

Before: Constant "stale: Profile, Summary" warnings even when feeds were healthy
After: No false staleness warnings - low-frequency feeds are expected behavior
```

### 2. Technical Implementation

- New components added (classes, functions, enums)
- Modified components with explanations
- Data flow changes if architectural

### 3. Features Added/Removed

- Tables listing all features with file locations
- Reasons for any removed features

### 4. Verification Evidence

- Test results (unit, integration, live)
- Specific examples with real data

The jira-workflow agent has detailed templates for this. Always delegate completion comments to it.

---

## Jira Quality Assurance Procedure

After creating or updating any Jira ticket, the jira-workflow agent MUST:

1. **Re-read the ticket** to verify it was created correctly
2. **Check completeness** against quality standards
3. **Fix any deficiencies** before reporting back
4. **Report confidence level** (✅ complete or ⚠️ needs attention)

---

## Plan-Ticket Alignment Procedure

Before implementation begins, persist the **full, exact** implementation plan to the Jira ticket. The ticket is the source of truth — plans discussed in conversation are lost if not persisted.

**How to persist plans:**

1. Pass the complete plan text to the jira-workflow agent with the **Verbatim Content Rule**
2. After the agent updates the ticket, re-read it to confirm **nothing was paraphrased or omitted**
3. If content was summarized or truncated, re-send with explicit correction
