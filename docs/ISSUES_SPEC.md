# Jira Issues Specification

This document defines the complete specification for Jira issue types, templates, workflows, and quality standards for the tastytrade-sdk project.

**Purpose**: This is a pure specification document that defines WHAT issues should contain and HOW they should be structured. Implementation details (HOW to create issues) are handled by the jira-workflow agent.

## Table of Contents

- [Overview](#overview)
- [Project Context](#project-context)
- [Issue Types](#issue-types)
- [Type Selection Logic](#type-selection-logic)
- [Issue Templates](#issue-templates)
- [Title Conventions](#title-conventions)
- [Test Evidence Requirements](#test-evidence-requirements)
- [What NOT to Include](#what-not-to-include)
- [Epic Governance](#epic-governance)
- [Sub-task Guidance](#sub-task-guidance)
- [Status Workflow](#status-workflow)
- [Validation Rules](#validation-rules)
- [Response Formats](#response-formats)
- [Priority and Defaults](#priority-and-defaults)

---

## Overview

All Jira issue operations follow these core principles:

1. **Type Intelligence**: Automatically select appropriate issue type based on request analysis
2. **Quality Enforcement**: Every ticket embeds mandatory Test Evidence Requirements
3. **Epic Management**: Agents can create, update, and link Epics for organizing initiatives
4. **Evidence First**: Production data verification is mandatory for all PRs
5. **Sub-tasks are Optional**: Use only when warranted (3+ pieces, parallelizable work)
6. **No Time Estimates**: Never include effort estimates, time predictions, or duration forecasts

---

## Project Context

- **Project Key**: `TT` (tastytrade-sdk)
- **Jira Instance**: https://mandeng.atlassian.net
- **Repository**: tastytrade-sdk
- **Main Branch**: main
- **Issue Types**: Epic (team-only), Story, Task, Bug, Sub-task

---

## Issue Types

### Epic

**Purpose**: Large business initiative spanning multiple Stories/Tasks

**Creation**: Agents CAN create and update Epics
- Epics are strategic planning tools for organizing work
- Can be created via jira-workflow agent
- Used to group related Stories/Tasks under a common initiative


### Story

**Purpose**: User-facing feature or capability that delivers direct value

**When to use**:
- End-user features
- New capabilities
- User workflows
- UI/UX improvements

**Keywords**: "feature", "as a user", "capability", "upload", "process", "view", "enable"

**Examples**:
- "Upload and Process PDF Documents"
- "Add CLI for markdown conversion"
- "Enable merged cell detection"

### Task

**Purpose**: Technical work, infrastructure, refactoring, internal improvements

**When to use**:
- Technical upgrades
- Refactoring
- Infrastructure setup
- Internal optimizations
- Test improvements

**Keywords**: "implement", "refactor", "upgrade", "migrate", "add tests", "setup", "optimize"

**Examples**:
- "Upgrade Python to 3.13"
- "Refactor table matching logic"
- "Optimize cell extraction performance"

### Bug

**Purpose**: Defect, error, unexpected behavior, broken functionality

**When to use**:
- Something broken
- Incorrect behavior
- Errors/exceptions
- Regression issues

**Keywords**: "fix", "error", "broken", "fails", "incorrect", "bug", "regression"

**Examples**:
- "PDF extraction fails on rotated pages"
- "Fix merged cell coordinate calculation"
- "Handle empty worksheets without errors"

### Sub-task

**Purpose**: Implementation piece under parent Story/Task/Bug

**When to use** (situational, optional):
- Parent has 3+ distinct implementation pieces
- Work can be parallelized across multiple PRs
- Complex bug requiring multiple separate fixes
- Clear breakdown of independent steps

**When NOT to use**:
- Single cohesive change (use checklist in parent instead)
- Only 1-2 simple steps
- Steps must be done together in one PR

**Examples**:
- "Create upload API endpoint" (under "Upload and Process PDF Documents" Story)
- "Add storage layer" (under parent Story)
- "Build upload UI component" (under parent Story)

---

## Type Selection Logic

When creating an issue, analyze the request and automatically select the appropriate type:

### Decision Tree

```
Is this a large strategic initiative spanning multiple Stories?
├─ YES → Epic
└─ NO → Continue...

Does this deliver direct value to end users?
├─ YES → Story
└─ NO → Continue...

Is this fixing broken/incorrect functionality?
├─ YES → Bug
└─ NO → Continue...

Is this technical work without user-visible changes?
├─ YES → Task
└─ NO → Continue...

Is this an implementation piece under an existing parent?
├─ YES → Sub-task (if warranted - 3+ pieces)
└─ NO → Ask for clarification
```

### Ambiguous Cases

If type cannot be determined:
1. Ask for clarification
2. Present options with reasoning
3. Wait for response before creating

**Example**:
```
Type clarification needed

"Refactor table matching logic" could be:
- Task: Internal technical refactoring (no user-visible changes)
- Story: If this changes user experience or adds new capabilities

Which is more appropriate for this work?
```

---

## Issue Templates

All templates below use **Jira markup format** (not markdown).

### Story Template

```
h2. User Story

*As a* [user / developer / stakeholder]
*I want* [feature/capability]
*So that* [benefit/value delivered]

h2. Acceptance Criteria

*CRITICAL*: Each criterion MUST specify how to verify with PRODUCTION DATA

h3. AC1: [Feature capability]

* *Verify by:* [How to verify - use realistic data, real workflows, actual scenarios]
* *Expected:* [Concrete, measurable outcome with numbers/specifics]
* *Show:* [What to demonstrate - file names, sizes, results]

h3. AC2: [Next capability]

* *Verify by:* [How to verify this works]
* *Expected:* [Concrete, measurable outcome]
* *Show:* [What to demonstrate]

h3. AC3: [Additional capability if needed]

* *Verify by:* [How to verify this works]
* *Expected:* [Concrete, measurable outcome]
* *Show:* [What to demonstrate]

h2. Story Points

*Points*: [1, 2, 3, 5, 8, 13]

h2. Priority

*Priority*: [High/Medium/Low - default to Medium]

h2. Technical Notes

*Follow project coding standards:*
* Strict type hints on all functions
* Follow project design patterns
* Add appropriate test coverage

h2. Test Evidence Requirements

*CRITICAL - CANNOT BE SKIPPED*

When implementing, the PR MUST include *functional evidence* for EACH acceptance criterion:

*Real Production/Realistic Data*
* Use actual production data or realistic files (NOT test fixtures from {{tests/fixtures/}})
* For file processing: show file names, sizes, and processing results
* For API/service: show realistic requests/responses
* For UI: show actual user workflows with real data

*Actual Usage Workflows*
* Demonstrate the feature working as specified in acceptance criteria
* Show integration with existing systems works
* Prove end-to-end workflows function correctly

*Concrete, Measurable Results*
* Specific file names, sizes, or identifiers
* Quantifiable outcomes (counts, durations, sizes)
* Sample output data relevant to the feature

*End-to-End Verification*
* Show feature works in application context
* Verify dependencies actually work (import and use them)
* Demonstrate configuration settings function

*Reference*: See [docs/PR_EVIDENCE_GUIDELINES.md|PR_EVIDENCE_GUIDELINES.md] for comprehensive standards and examples.

*Evidence Checklist:*
* [ ] Tested with realistic data appropriate to the feature
* [ ] Documented concrete, measurable results (file sizes, counts, etc.)
* [ ] Showed feature working as specified in ACs
* [ ] Demonstrated end-to-end in realistic context
* [ ] Included specific examples with verifiable details

h2. Definition of Done

* [ ] Code implemented and tested
* [ ] *Functional evidence provided for EACH acceptance criterion*
* [ ] Unit tests passing
* [ ] Type checking clean
* [ ] Linting clean
* [ ] Documentation updated
* [ ] Code reviewed and approved
* [ ] Merged to main branch

h2. Dependencies

[Other stories or tasks that must be completed first]
* None

h2. Related Epic

Epic: [TT-XXX or leave blank if unclear]

h2. Additional Context

[Screenshots, examples, diagrams, or other helpful information]
```

---

### Task Template

```
h2. Task Description

[Clear description of what technical work needs to be done]

h2. Parent Story

[Link to the user story this task belongs to, if applicable]
Story: [TT-XXX or None]

h2. Implementation Details

[Technical approach or specific requirements - use checklist for steps]

* [ ] Step 1
* [ ] Step 2
* [ ] Step 3

h2. Priority

*Priority*: [High/Medium/Low - default to Medium]

h2. Test Evidence Requirements

*CRITICAL - CANNOT BE SKIPPED*

When creating PR, you MUST provide *functional evidence* for each requirement:

*For EACH step in Implementation Details:*
# Use REAL production/realistic data (NOT test fixtures from {{tests/}})
# Show concrete, measurable results
# Demonstrate feature working as specified
# Prove it works in realistic application context

*Evidence Checklist:*
* [ ] Tested with realistic data appropriate to the feature
* [ ] Documented concrete, measurable results
* [ ] Showed feature working as specified
* [ ] Demonstrated end-to-end in realistic context
* [ ] Included specific examples with verifiable details

*Reference*: See [docs/PR_EVIDENCE_GUIDELINES.md|PR_EVIDENCE_GUIDELINES.md]

h2. Definition of Done

* [ ] Code implemented and tested
* [ ] *Functional evidence provided for EACH acceptance criterion*
* [ ] Unit tests passing
* [ ] Type checking clean
* [ ] Linting clean
* [ ] Documentation updated
* [ ] Code reviewed and approved
* [ ] Merged to main branch

h2. Dependencies

[Other tasks that must be completed first]
* None

h2. Technical Notes

*Follow project coding standards:*
* Strict type hints on all functions
* Follow project design patterns
* Add appropriate test coverage

h2. Related Epic

Epic: [TT-XXX or leave blank if unclear]
```

---

### Bug Template

```
h2. Bug Description

[Clear description of what is broken or behaving incorrectly]

h2. Steps to Reproduce

# [First step]
# [Second step]
# [Third step]

h2. Expected Behavior

[What should happen]

h2. Actual Behavior

[What actually happens - the bug]

h2. Environment

* *Python Version*: [e.g., 3.13]
* *OS*: [e.g., Ubuntu 22.04, macOS 14]
* *Relevant Dependencies*: [e.g., pydantic 2.10]

h2. Error Messages / Logs

{code}
[Paste any error messages or relevant log output]
{code}

h2. Severity

*Severity*: [Critical/High/Medium/Low]
* *Critical*: System down, data loss, security issue
* *High*: Major functionality broken, no workaround
* *Medium*: Functionality impaired, workaround exists
* *Low*: Minor issue, cosmetic problem

h2. Acceptance Criteria for Fix

h3. AC1: Bug no longer occurs

* *Verify by:* [Reproduce original steps - should now work]
* *Expected:* [Correct behavior observed]
* *Show:* [Concrete evidence it's fixed]

h3. AC2: No regressions introduced

* *Verify by:* [Run existing workflows/tests]
* *Expected:* [All existing functionality still works]
* *Show:* [Evidence of regression testing]

h2. Test Evidence Requirements

*CRITICAL - CANNOT BE SKIPPED*

When creating PR with fix, you MUST provide *functional evidence*:

*Reproduction*
* Show you can reproduce the original bug (before fix)
* Document the error/incorrect behavior

*Fix Verification*
* Show the bug no longer occurs (after fix)
* Use realistic data/scenarios that triggered the bug
* Demonstrate correct behavior with concrete examples

*Regression Testing*
* Prove existing workflows still function
* Show related features unaffected
* Demonstrate end-to-end scenarios work

*Evidence Checklist:*
* [ ] Reproduced original bug (before fix)
* [ ] Verified bug fixed (after fix) with realistic scenario
* [ ] Tested for regressions in related functionality
* [ ] Documented concrete results showing correct behavior
* [ ] Included specific examples with verifiable details

*Reference*: See [docs/PR_EVIDENCE_GUIDELINES.md|PR_EVIDENCE_GUIDELINES.md]

h2. Definition of Done

* [ ] Code implemented and tested
* [ ] *Functional evidence provided for EACH acceptance criterion*
* [ ] Unit tests passing
* [ ] Type checking clean
* [ ] Linting clean
* [ ] Documentation updated
* [ ] Code reviewed and approved
* [ ] Merged to main branch

h2. Root Cause Analysis

[Optional: What caused the bug? Understanding helps prevent similar issues]

h2. Dependencies

[Any blockers or related issues]
* None

h2. Related Epic

Epic: [TT-XXX or leave blank if unclear]
```

---

### Sub-task Template

**NOTE**: Use only when warranted (3+ implementation pieces, parallelizable work)

```
h2. Sub-task Description

[Clear description of this specific implementation piece]

*Parent*: [TT-XXX - REQUIRED, must specify parent]

h2. What This Accomplishes

[How this sub-task contributes to the parent ticket goal]

h2. Implementation Steps

* [ ] Step 1
* [ ] Step 2
* [ ] Step 3

h2. Acceptance Criteria

[Simplified - focus on this piece only, not entire parent goal]

* *Verify by:* [How to verify this piece works]
* *Expected:* [Specific outcome for this sub-task]
* *Show:* [What to demonstrate]

h2. Priority

*Priority*: [Inherits from parent - typically same as parent]

h2. Test Evidence Requirements

*CRITICAL - CANNOT BE SKIPPED*

Even for Sub-tasks, PR MUST include *functional evidence*:

* Demonstrate this piece works with realistic data
* Show concrete results specific to this sub-task
* Prove integration with parent ticket context

*Evidence Checklist:*
* [ ] Tested with realistic data
* [ ] Documented concrete results
* [ ] Showed sub-task working as specified
* [ ] Verified integration with parent context

*Reference*: See [docs/PR_EVIDENCE_GUIDELINES.md|PR_EVIDENCE_GUIDELINES.md]

h2. Definition of Done

* [ ] Code implemented and tested
* [ ] *Functional evidence provided for EACH acceptance criterion*
* [ ] Unit tests passing
* [ ] Type checking clean
* [ ] Linting clean
* [ ] Documentation updated
* [ ] Code reviewed and approved
* [ ] Merged to main branch

h2. Technical Notes

*Follow project coding standards:*
* Strict type hints on all functions
* Follow project design patterns
* Add appropriate test coverage

h2. Related Epic

[Inherited from parent - usually same as parent's Epic]
Epic: [TT-XXX or leave blank]
```

---

### Epic Template

```
h2. Epic Overview

[Clear description of what this epic will deliver]

h2. Business Value

[Why this epic is important and what value it brings]

h2. Success Metrics

* [ ] Metric 1
* [ ] Metric 2
* [ ] Metric 3

h2. User Stories

[List the user stories that make up this epic]
* [ ] Story 1: As a..., I want..., so that...
* [ ] Story 2: As a..., I want..., so that...

h2. Dependencies

* None

h2. Target Completion

Sprint/Milestone: [target]

h2. Technical Considerations

* Strict type hints on all functions
* Follow project design patterns
* Add appropriate test coverage
* Follow project architecture guidelines
```

---

## Title Conventions

**Format**: Clear and descriptive - **NO redundant prefixes**

Issue type is already shown in Jira - don't duplicate it in the title.

### Good Titles

- **Epic**: `Core Infrastructure - Models, Protocols, Config`
- **Story**: `Upload and Process PDF Documents`
- **Task**: `Upgrade Python to 3.13`
- **Bug**: `PDF extraction fails on rotated pages`
- **Sub-task**: `Create upload API endpoint`

### Bad Titles

- `[EPIC] Core Infrastructure`
- `[STORY] Upload and Process...`
- `As a user, I want to upload PDFs` (user story format in description, not title)
- `TASK: Upgrade Python...`
- `[BUG] PDF extraction...`
- `[SUBTASK] Create...`

---

## What NOT to Include

**CRITICAL - These items must NEVER appear in Jira issues:**

### Time Estimates
**NEVER include**:
- "Estimated Effort: X weeks/days/hours"
- "Implementation time: X"
- "Total duration: X"
- "Expected to take X"
- Any predictions about how long work will take

**Why**: Time estimates are based on non-agentic workflows, add no accountability value, and are not read. Agentic development timelines are unpredictable and estimates are misleading.

### Oversimplified Examples
**NEVER include**:
- Example usage that doesn't reflect real business scenarios
- Simplified output that hides actual complexity
- Mock data that doesn't represent production usage
- Examples with technical inaccuracies

**Why**: Misleading examples pollute context streams and lead to incorrect implementations. If examples are needed, they must be technically accurate and reflect real-world usage.

### Generic Boilerplate
**NEVER include**:
- "To be determined"
- "More details coming soon"
- Copy-pasted sections without customization
- Placeholder text that adds no value

**Why**: Every section should provide actionable, specific information. Remove sections that don't add value rather than filling them with placeholders.

---

## Test Evidence Requirements

**MANDATORY FOR ALL ISSUE TYPES**

Every PR must include functional evidence demonstrating the feature/fix works with production data.

### Core Requirements

#### 1. Real Production/Realistic Data

**Use**:
- Actual production data or realistic files
- Realistic files/scenarios relevant to the feature
- Real API requests/responses
- Actual user workflows

**DON'T Use**:
- Test fixtures for functional evidence (unit tests only)
- Minimal test data
- Synthetic examples that don't reflect real usage

#### 2. Actual Usage Workflows

**Show**:
- Feature working as specified in acceptance criteria
- Integration with existing systems
- End-to-end workflows functioning correctly
- Real-world use cases

#### 3. Concrete, Measurable Results

**Provide**:
- Specific file names and sizes
- Quantifiable outcomes (counts, durations, percentages)
- Sample output data
- Performance metrics where relevant

#### 4. End-to-End Verification

**Demonstrate**:
- Feature works in full application context
- Dependencies function correctly
- Configuration settings work
- No regressions in existing functionality

### Evidence Checklist

Every PR must complete:

- [ ] Tested with realistic data appropriate to the feature
- [ ] Documented concrete, measurable results (file sizes, counts, etc.)
- [ ] Showed feature working as specified in acceptance criteria
- [ ] Demonstrated end-to-end in realistic context
- [ ] Included specific examples with verifiable details

### Type-Specific Evidence

**Story**:
- Demonstrate each AC met with real user workflows
- Show feature delivering promised value
- Provide concrete usage examples

**Task**:
- Demonstrate each implementation step works
- Show technical improvement with measurable results
- Prove changes integrate correctly

**Bug**:
- Reproduce original bug (before fix)
- Verify bug fixed (after fix) with realistic scenario
- Demonstrate no regressions in related functionality

**Sub-task**:
- Demonstrate this piece works with realistic data
- Show concrete results specific to this sub-task
- Prove integration with parent ticket context

---

## Epic Governance

### Can Create and Update Epics

**Epics are strategic planning tools** that organize related work into initiatives.

**Agents CAN**:
* Create new Epic issues when requested
* Update Epic descriptions and fields
* Link Stories/Tasks/Bugs to Epics
* Search and retrieve Epic details

**Epic Creation Guidelines**:
* Use comprehensive descriptions with strategic context
* Include: Overview, Components, Implementation Phases, Success Criteria
* Properly format descriptions using Jira markup (not markdown)
* Link child issues using parent-key parameter

### Linking to Existing Epics

**Decision logic**:

1. **Epic explicitly specified** -> Link to it
   - "Link to Epic TT-XXX"
   - "This is for the [epic name] epic"

2. **Epic obvious from context** -> Link automatically
   - Match the work to the appropriate epic based on project context

3. **Epic unclear** -> Leave blank
   - Add note: "Epic assignment pending - team to assign during planning"


---

## Sub-task Guidance

**Sub-tasks are OPTIONAL, situational tools** - not required for every ticket.

### When to Use Sub-tasks

**Consider sub-tasks when**:
- Story/Task has **3+ distinct implementation pieces**
- Work can be **parallelized** across multiple PRs
- Complex Bug requiring **multiple separate fixes**
- Clear **breakdown** of independent steps

### When NOT to Use Sub-tasks

**Don't use sub-tasks when**:
- Single, cohesive change (use checklist in description instead)
- Only 1-2 simple steps
- Steps must be done together in one PR

### Sub-task Structure

**Can be created under**:
- Story (implementation pieces)
- Task (technical breakdown)
- Bug (complex fix steps)

**Each Sub-task**:
- Has its own status (To Do -> In Progress -> In Review -> Done)
- Can be assigned independently
- Can be automated independently
- Inherits context from parent
- Requires functional evidence (same standards as parent types)

### Example

```
Story: TT-50 - Upload and Process PDF Documents
├─ Sub-task: TT-51 - Create upload API endpoint
├─ Sub-task: TT-52 - Implement file validation
├─ Sub-task: TT-53 - Add storage layer
└─ Sub-task: TT-54 - Build upload UI component
```

---

## Status Workflow

### Standard Workflow

**Automated via GitHub workflows** (not manual):

```
To Do → In Progress → In Review → Done
```

### Status Meanings

- **To Do**: Refined, clear ACs, ready to start
- **In Progress**: Currently being worked on
- **In Review**: PR created, awaiting review
- **Done**: Complete and merged

### Status Transitions

**Automated via `.github/workflows/jira-transition.yml`**:

- Branch created -> Jira moves to "In Progress"
- PR opened -> Jira moves to "In Review"
- PR merged -> Jira moves to "Done"

**Agent Role**: Read-only status awareness. Do NOT manually transition tickets.

### Workflow Example

1. Agent creates Jira ticket TT-6 (Story)
2. Developer creates branch `feature/TT-6-description`
3. GitHub workflow -> TT-6 moves to "In Progress"
4. Developer implements feature, creates PR
5. GitHub workflow -> TT-6 moves to "In Review"
6. PR merged to main
7. GitHub workflow -> TT-6 moves to "Done"

---

## Validation Rules

### Before Creating Any Ticket

**Must validate**:
- Type determined (Story/Task/Bug/Sub-task or Epic)
- Title is clear and descriptive
- Title has NO redundant prefix ([STORY], [TASK], etc.)
- Template selected matches type
- Required fields for that type present
- Parent specified (if Sub-task)
- Epic link determined or explicitly left blank
- Project key is "TT"

**If validation fails**:
```
Cannot create issue
Reason: [specific problem]
Need: [what's missing or wrong]
```

### Type-Specific Validation

**Story**:
- Has user story format (As a.../I want.../So that...)
- Has acceptance criteria with Verify/Expected/Show
- Has Test Evidence Requirements section
- Has Definition of Done

**Task**:
- Has clear task description
- Has implementation details/steps
- Has Test Evidence Requirements
- Has Definition of Done

**Bug**:
- Has bug description
- Has steps to reproduce
- Has expected vs actual behavior
- Has severity
- Has Test Evidence Requirements (fix verification)

**Sub-task**:
- Has parent ticket specified
- Has clear description of piece
- Has simplified acceptance criteria
- Has Test Evidence Requirements

---

## Response Formats

### Success: Issue Created

```
Created [Type] TT-XXX
Title: [title]
Type: [Story/Task/Bug/Sub-task]
Priority: [priority]
Status: To Do
Parent Epic: [TT-YYY or None]
Parent Issue: [TT-ZZZ - if Sub-task]
URL: https://mandeng.atlassian.net/browse/TT-XXX
```

### Error: Cannot Create

```
Cannot create issue
Reason: [specific problem]
Need: [what's required]
Suggestion: [how to fix]
```

### Error: Epic Creation Requested

```
Cannot create Epic

Epics are strategic planning tools managed by the team.
Please create Epic manually in Jira, then I can link issues to it.
```

### Info: Clarification Needed

```
Type clarification needed

"[request]" could be:
- [Option 1]: [reasoning]
- [Option 2]: [reasoning]

Which is more appropriate?
```

---

## Priority and Defaults

### Priority Defaults

If priority not specified:
- **Epic**: High (strategic)
- **Story**: Medium
- **Task**: Medium
- **Bug**: Based on severity
  - Critical -> High
  - High -> High
  - Medium -> Medium
  - Low -> Low
- **Sub-task**: Inherit from parent

### Smart Defaults

**Status**:
- All new issues: To Do

**Assignee**:
- Unassigned (team assigns during planning)

**Epic Linking**:
- If context clearly indicates Epic -> Link automatically
- If unclear -> Leave blank, note "Epic assignment pending"

---

## Integration Patterns

### GitHub Workflow Integration

**Issue Management Agent Responsibilities**:
- Create Jira tickets with quality standards
- Link tickets to Epics
- Manage ticket metadata
- Enforce Test Evidence Requirements

**GitHub Automation Responsibilities** (automated workflows):
- Listen to GitHub events (branch create, PR open, PR merge)
- Automatically transition Jira tickets based on events
- No manual status management needed

**Pull Request Agent Responsibilities**:
- Create PRs with functional evidence
- Link PRs to Jira tickets
- Manage PR reviews and merging

---

## Technical Standards

All tickets reference these project standards:

### Code Quality
- **Type Checking**: Project type checker (zero errors)
- **Linting**: Project linter (zero errors)
- **Testing**: Project test framework (80%+ coverage target)

### Development
- **Async**: async/await for I/O operations where appropriate
- **Configuration**: Environment-based configuration management
- **Environment Variables**: Override defaults, never hardcode secrets

---

## Implementation Completion Comments

When work on a Jira ticket is complete, a comprehensive implementation comment MUST be added to document the changes.

### Required Sections

#### 1. Problem Statement
Brief description of what problem was solved and why it was needed.

#### 2. Expected Behaviors (CRITICAL)
Document all behavioral changes from the user/operational perspective. Use Before/After format:

```
h3. [Behavior Name]
*Before:* [How it worked before / what the problem was]
*After:* [How it works now / what the improvement is]
```

This section is the MOST IMPORTANT - it shows the value delivered from the user's perspective.

#### 3. Technical Implementation
- New components (classes, functions, enums with brief descriptions)
- Modified components (what changed and why)
- Data flow changes (if architectural)
- Dependency chains (if relevant)

#### 4. Features Added/Removed Tables
Use Jira table format:

```
h2. Features Added

|| Feature || File || Description ||
| [Feature name] | [filename.py] | [Brief description] |

h2. Features Removed

|| Feature || File || Reason ||
| [Feature name] | [filename.py] | [Why removed] |
```

#### 5. Verification
- Test results (unit, integration, live testing)
- Specific evidence showing the feature works
- PR link and file change summary

### Quality Standards

- **Expected Behaviors**: Every significant behavioral change must be documented
- **Before/After**: Always show the contrast, not just the new state
- **Specificity**: Use concrete examples ("8s ago") not vague descriptions ("improved")
- **Completeness**: All features added/removed must be listed
- **Evidence**: Include verification that proves it works

### Quality Assurance

After adding an implementation comment, the agent MUST:
1. Re-read the ticket to verify the comment was added correctly
2. Check that all sections are complete
3. Verify Expected Behaviors accurately reflect the changes
4. Report any deficiencies to the user

---

## Summary

This specification defines:

1. **5 Issue Types**: Epic, Story, Task, Bug, Sub-task
2. **Intelligent Type Selection**: Automatic analysis-based type determination
3. **Comprehensive Templates**: All issue types with embedded quality standards
4. **Mandatory Evidence Requirements**: Production data verification for all PRs
5. **Epic Management**: Agents can create, update, and link Epics
6. **Sub-task Guidance**: Optional, situational use (3+ pieces, parallelizable)
7. **Automated Workflows**: GitHub-driven status transitions
8. **Clear Validation Rules**: Ensure quality before creation
9. **Standard Response Formats**: Consistent success/error messaging
10. **Integration Patterns**: Clear separation of responsibilities
11. **Implementation Completion Comments**: Mandatory documentation with Expected Behaviors, Technical Implementation, and Verification

**Implementation Note**: This is a specification document. The jira-workflow agent determines the implementation mechanism (Skills, MCP tools, or other approaches) appropriate for the project.

All agents and developers must follow these specifications when creating or managing Jira issues.
