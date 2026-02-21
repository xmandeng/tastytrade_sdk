# GitHub Workflow Specification

This document defines the complete specification for GitHub workflows, pull requests, branching strategies, and code review standards for the tastytrade-sdk project.

**Purpose**: This is a pure specification document that defines WHAT pull requests should contain and HOW git workflows should be structured. Implementation details (HOW to execute operations) are handled by the github-workflow agent.

## Table of Contents

- [Overview](#overview)
- [Repository Context](#repository-context)
- [Branch Naming Conventions](#branch-naming-conventions)
- [Commit Message Format](#commit-message-format)
- [Pull Request Standards](#pull-request-standards)
- [Functional Evidence Requirements](#functional-evidence-requirements)
- [PR Review Process](#pr-review-process)
- [Merge Strategies](#merge-strategies)
- [Integration with Jira](#integration-with-jira)
- [Git Workflow Patterns](#git-workflow-patterns)
- [Response Formats](#response-formats)
- [Quality Gates](#quality-gates)

---

## Overview

All GitHub operations follow these core principles:

1. **Jira Integration**: Every PR must reference a Jira ticket (no GitHub issue numbers)
2. **Functional Evidence**: PRs must demonstrate acceptance criteria met with production data
3. **Consistent Naming**: Branch and commit conventions tied to Jira tickets
4. **Quality Gates**: Type checking, linting, and tests must pass before merge
5. **Clear Communication**: Structured PR descriptions with concrete evidence

---

## Repository Context

### Repository Information

- **Owner**: Auto-detected from git remote (auto-detected)
- **Repository**: Auto-detected from git remote (currently: tastytrade-sdk)
- **Main Branch**: main
- **Jira Instance**: `${ATLASSIAN_SITE_NAME}` (e.g., https://mandeng.atlassian.net)
- **Project Key**: `${JIRA_PROJECT_PREFIX}` (e.g., TT)
- **Project Label**: `${JIRA_PROJECT_LABEL}` (e.g., tastytrade-sdk)

### Workflow Integration

- Branch creation → Jira ticket moves to "In Progress" (automated)
- PR creation → Jira ticket moves to "In Review" (automated)
- PR merge → Jira ticket moves to "Done" (automated)

---

## Branch Naming Conventions

### Standard Format

```
<type>/<jira-key>-<brief-description>
```

### Branch Types

**feature/** - New features or capabilities

- Example: `feature/TT-87-migrate-to-jira`
- Example: `feature/TT-45-add-pdf-upload`

**bugfix/** - Bug fixes

- Example: `bugfix/TT-23-fix-extraction-error`
- Example: `bugfix/TT-101-handle-empty-cells`

**task/** - Technical work (optional, can use feature/)

- Example: `task/TT-78-upgrade-python`
- Example: `task/TT-92-refactor-matching`

### Branch Naming Rules

Good Examples:

- `feature/TT-87-migrate-to-jira`
- `bugfix/TT-23-fix-extraction-error`
- `feature/TT-120-implement-claim-mechanism`

Bad Examples:

- `feature-87` (no Jira key)
- `fix-bug` (no ticket reference)
- `TT-87` (no type prefix or description)
- `feature/87-migrate` (missing project key)

### Branch Lifecycle

1. **Create**: Branch from `main` with proper naming
2. **Work**: Make commits with descriptive messages
3. **Push**: Push to remote repository
4. **PR**: Create pull request from branch → main
5. **Merge**: Squash or merge commits
6. **Delete**: Branch automatically deleted after merge

---

## Commit Message Format

### Standard Format

```
TT-XXX: Brief description of changes

Detailed explanation of what changed and why.
Can be multiple lines.

- Bullet point for specific change 1
- Bullet point for specific change 2
```

### Commit Message Rules

**First Line** (required):

- Format: `TT-XXX: Brief description`
- Max 72 characters
- Use imperative mood ("Add" not "Added")
- Capitalize first word

**Body** (optional but recommended):

- Blank line after first line
- Explain what and why (not how)
- Wrap at 72 characters
- Use bullets for multiple changes

### Commit Examples

Good Example:

```
TT-87: Migrate from GitHub Issues to Jira

Replaced GitHub Issues with Jira for improved project management:
- Migrated all agent configurations
- Updated documentation references
- Added functional validation
- Removed GitHub issue templates
```

Bad Examples:

```
Fixed bug (no ticket reference)

TT-87 migrate to jira (no colon, not descriptive)

Updated files (vague, no context)
```

---

## Pull Request Standards

### PR Title Format

**Required Format**: `TT-XXX: Brief description of changes`

Good Examples:

- `TT-87: Migrate from GitHub Issues to Jira`
- `TT-120: Implement automation:claimed label system`
- `TT-45: Add PDF upload and processing`

Bad Examples:

- `#87: Migrate to Jira` (GitHub issue number, not Jira)
- `Migrate from GitHub Issues to Jira` (no ticket reference)
- `TT-87 Migrate to Jira` (missing colon)

### PR Body Structure

**Required Sections**:

```markdown
## Summary
[Brief 2-3 sentence description of what changed and why]

## Related Jira Issue
**Jira**: [TT-XXX](https://mandeng.atlassian.net/browse/TT-XXX)

## Acceptance Criteria - Functional Evidence

### AC1: [Criterion from Jira ticket]

**Real Example: [Specific usage scenario]**
```[language]
[Code demonstrating feature with production/realistic data]
[Show actual commands run and their output]
```

**Results:**

- [Specific measurable outcome 1]
- [Specific measurable outcome 2]
- [Specific measurable outcome 3]

**Production Data Tested:**

- [File/data 1]: [details] → [results]
- [File/data 2]: [details] → [results]

---

### AC2: [Next criterion]

[Repeat same pattern for each acceptance criterion]

---

## Test Evidence

- All tests passing (`just test`)
- Coverage: [X]% (target: 80%+) (`just test-cov`)
- Pre-commit hooks passed (linting, type checking, formatting - enforced at commit level)

**IMPORTANT**: Test evidence should be documented in the PR description or PR comments, NOT as separate files committed to the repository (e.g., TEST_EVIDENCE.md). This keeps the repository clean while maintaining evidence accessibility for review.

## Changes Made

- [File/module 1]: [What was changed and why]
- [File/module 2]: [What was changed and why]
- [File/module 3]: [What was changed and why]
```

### PR Body Guidelines

**Summary Section**:
- 2-3 sentences maximum
- What changed (not how)
- Why it changed (business value)
- High-level impact

**Jira Link**:
- Always use full URL format
- Link should be clickable
- Must match ticket in PR title

**Acceptance Criteria Evidence**:
- One section per AC from Jira ticket
- Must show functional evidence (not just tests)
- Use production/realistic data
- Provide concrete, measurable results
- See [Functional Evidence Requirements](#functional-evidence-requirements)

**Test Evidence**:
- Confirm all quality gates passed
- Include coverage percentage
- Note any test improvements

**Changes Made**:
- List key files/modules changed
- Explain what changed in each
- Helps reviewers understand scope

---

## Functional Evidence Requirements

**CRITICAL PRINCIPLE**: Test Evidence ≠ Functional Evidence

Passing tests prove code works in isolation. Functional evidence proves the feature works in production context.

### Core Requirements

For EVERY acceptance criterion, provide:

#### 1. Real Production/Realistic Data

**Use**:
- Actual production data (e.g., from `inputs/` directory)
- Realistic files/scenarios relevant to the feature
- Real API requests/responses
- Actual user workflows

**DON'T Use**:
- Test fixtures from `tests/fixtures/` (unit tests only)
- Minimal/synthetic test data
- Mock data that doesn't reflect reality

**Examples**:
- `inputs/production_tables.json` (21 tables, 2.3MB)
- `tests/fixtures/sample.json` (2 tables, 150 bytes)

#### 2. Actual Usage Workflows

**Show**:
- Feature working as specified in acceptance criteria
- Integration with existing systems
- End-to-end workflows functioning correctly
- Real-world use cases

**Examples**:
```python
# Good - Shows real workflow
from myproject import DocumentProcessor

processor = DocumentProcessor()
tables = await processor.load_tables('inputs/production_data.json')
print(f"Loaded {len(tables)} tables")  # Loaded 21 tables

# Search and filter (downstream workflow)
results = [t for t in tables if 'revenue' in t.name.lower()]
print(f"Found {len(results)} revenue tables")  # Found 3 revenue tables

# Bad - Just shows test passed
assert test_load_tables() == True  # Test passed
```

#### 3. Concrete, Measurable Results

**Provide**:

- Specific file names and sizes
- Quantifiable outcomes (counts, durations, percentages)
- Sample output data
- Performance metrics where relevant

**Examples**:

- "Processed 3 production files (4.2MB total) in 1.8s"
- "Extracted 21 tables with 847 total cells"
- "Configuration override works: `custom/data.json` → loaded successfully"
- ~~"Feature works as expected"~~
- ~~"All tests pass"~~

#### 4. End-to-End Verification

**Demonstrate**:

- Feature works in full application context
- Dependencies function correctly
- Configuration settings work
- No regressions in existing functionality

**Examples**:

```python
# Good - End-to-end verification
import sys
print(sys.version)  # 3.13.8 - concrete version

# Real application workflow
processor = DocumentProcessor()
tables = await processor.load('inputs/real_data.json')
print(f"Loaded {len(tables)} tables")  # Concrete result

# Verify downstream works
results = await processor.search(tables, 'revenue')
print(f"Search returned {len(results)} matches")  # Proves integration

# Bad - Only unit test
def test_load():
    assert loader.load('fixtures/test.json') is not None
```

### Evidence Checklist

Before submitting PR, verify:

- [ ] Demonstrated each AC with **real production data** (not fixtures)
- [ ] Showed **actual usage patterns** (not just "tests pass")
- [ ] Proved **downstream workflows** still function
- [ ] Used **concrete examples** anyone can verify
- [ ] Provided **file names, sizes, and results** for production data
- [ ] Showed **real commands** and their **actual output**
- [ ] Demonstrated feature works **end-to-end** in application context
- [ ] **Evidence documented in PR description/comments** (NOT as committed test files)

### Evidence by AC Type

#### Feature Functionality ACs

**Requirements**:

- Demonstrate with real production/realistic data
- Show concrete, measurable results
- Display sample output proving it works
- Verify data/results are correct and usable

**Example**:

```markdown
### AC1: JSON loader successfully loads production table data

**Real Example: Loading 3 production financial documents**

```python
from myproject.document import JSONTableLoader

loader = JSONTableLoader()

# Production file 1
tables_1 = await loader.load('inputs/aapl_10q_q3_2024_tables.json')
print(f"Loaded {len(tables_1)} tables from AAPL 10-Q")

# Production file 2
tables_2 = await loader.load('inputs/msft_10k_2024_tables.json')
print(f"Loaded {len(tables_2)} tables from MSFT 10-K")
```

**Results:**

- AAPL 10-Q: 8 tables loaded (1.2MB file)
- MSFT 10-K: 13 tables loaded (2.3MB file)
- All tables have valid structure (name, headers, rows)
- Data types correctly parsed (numbers, strings, dates)

**Production Data Tested:**

- `aapl_10q_q3_2024_tables.json`: 1.2MB → 8 tables, 324 cells
- `msft_10k_2024_tables.json`: 2.3MB → 13 tables, 523 cells
- `googl_10k_2024_tables.json`: 1.8MB → 11 tables, 412 cells

```

#### Code Removal ACs

**Requirements**:
- Prove old modules cannot be imported
- Show what modules ARE available
- Verify file structure confirms deletion

**Example**:
```markdown
### AC2: All PDF processing code removed

**Real Example: Attempting to use removed functionality**

```python
# Attempt to import removed PDF modules
try:
    from myproject.document import pdf_processor
except ModuleNotFoundError:
    print("pdf_processor module no longer exists")

try:
    from myproject.document import PDFProcessor
except ImportError:
    print("PDFProcessor class no longer available")

# Show what IS available now
from myproject import document
available = [x for x in dir(document) if not x.startswith('_')]
print(f"Available modules: {available}")
# ['DocumentProcessor', 'JSONTableLoader']
```

**Results:**

- Cannot import `pdf_processor` module (ModuleNotFoundError)
- Cannot import `PDFProcessor` class (ImportError)
- Only new modules available: JSONTableLoader, DocumentProcessor
- File system confirms deletion: `src/myproject/document/` contains only json_loader.py

```

#### Dependency Change ACs

**Requirements**:
- Prove dependency cannot be imported (if removed)
- Show it's not in pyproject.toml
- Verify lock file doesn't include it
- Demonstrate alternative works (if replaced)

**Example**:
```markdown
### AC3: docling dependency removed, replaced with direct JSON loading

**Real Example: Verifying docling removal and replacement**

```bash
# Attempt to import removed dependency
$ python -c "import docling"
ModuleNotFoundError: No module named 'docling'
docling cannot be imported

# Check pyproject.toml
$ grep docling pyproject.toml
(no output)
docling not in dependencies

# Check lock file
$ grep docling uv.lock
(no output)
docling not in lock file

# Show replacement works
$ python -c "from myproject.document import JSONTableLoader; print('JSONTableLoader available')"
JSONTableLoader available
```

**Results:**

- docling removed from all dependency files
- docling cannot be imported
- Alternative (JSONTableLoader) available and functional
- Production workflows work without docling

```

#### Configuration ACs

**Requirements**:
- Show default value works
- Demonstrate override via environment variable
- Prove it's actually used in the application
- Test with realistic values

**Example**:
```markdown
### AC4: Configuration allows specifying JSON file path

**Real Example: Testing configuration with defaults and overrides**

```python
from myproject.config import AppConfig
import os

# Test default configuration
config = AppConfig()
print(f"Default path: {config.tables_json_path}")
# Default path: inputs/tables.json

# Test environment variable override
os.environ['TABLES_JSON_PATH'] = 'custom/production_data.json'
config = AppConfig()
print(f"Override path: {config.tables_json_path}")
# Override path: custom/production_data.json

# Prove it's used in application
from myproject import DocumentProcessor
processor = DocumentProcessor()
# Internally uses config.tables_json_path
tables = await processor.load_tables()
print(f"Loaded from configured path: {len(tables)} tables")
```

**Results:**

- Default: `inputs/tables.json` (confirmed)
- Override: `custom/production_data.json` (works via env var)
- Application uses configured path (loaded 21 tables)
- Both absolute and relative paths supported

```

#### Version Upgrade ACs

**Requirements**:
- Show actual version running
- Run real application code (not just tests)
- Verify all dependencies compatible
- Demonstrate production workloads succeed

**Example**:
```markdown
### AC1: Application runs on Python 3.13

**Real Example: Running production workloads on Python 3.13**

```python
import sys
print(f"Python version: {sys.version}")
# Python version: 3.13.8 (main, Oct 8 2025)

# Run real application workflow
from myproject import DocumentProcessor

processor = DocumentProcessor()
tables = await processor.load_tables('inputs/production_data.json')
print(f"Loaded {len(tables)} tables on Python 3.13")
# Loaded 21 tables on Python 3.13

# Verify dependencies work
import pydantic
print(f"pydantic: {pydantic.__version__}")  # 2.12.0
```

**Results:**

- Python 3.13.8 running (confirmed)
- Production workflow successful (21 tables loaded)
- All dependencies compatible and functional
- No compatibility issues found

```

#### Integration/Compatibility ACs

**Requirements**:
- Show feature integrates with existing systems
- Demonstrate workflows continue to function
- Verify all necessary interfaces exist
- Prove no regressions in dependent functionality

**Example**:
```markdown
### AC5: Existing search and filter workflows continue to function

**Real Example: Testing downstream workflows with new JSON loader**

```python
from myproject import DocumentProcessor

processor = DocumentProcessor()

# Load tables using new JSON loader
tables = await processor.load_tables('inputs/production_data.json')
print(f"Loaded {len(tables)} tables")

# Test search functionality (downstream consumer)
revenue_tables = [t for t in tables if 'revenue' in t.name.lower()]
print(f"Search found {len(revenue_tables)} revenue tables")
# Search found 3 revenue tables

# Test filter functionality (downstream consumer)
large_tables = [t for t in tables if len(t.rows) > 10]
print(f"Filter found {len(large_tables)} tables with >10 rows")
# Filter found 8 tables with >10 rows

# Test extraction workflow (end-to-end)
for table in revenue_tables:
    data = await processor.extract_values(table, ['Q3 2024', 'Q2 2024'])
    print(f"Extracted {len(data)} values from {table.name}")
```

**Results:**

- Search workflow works (found 3 revenue tables)
- Filter workflow works (found 8 large tables)
- Extraction workflow works (extracted values from all 3 tables)
- No regressions - all existing functionality preserved

```

### Common Evidence Mistakes

#### Mistake 1: Only showing test results

```markdown
## Test Evidence
- test_load_json PASSED
- test_extract_tables PASSED
- All 50 tests pass
```

**Problem**: Doesn't show feature works with production data

**Fix**: Show loading real production files with concrete results

---

#### Mistake 2: Using sample/mock data

```markdown
tables = await loader.load('tests/fixtures/sample.json')
Loaded 2 tables
```

**Problem**: Test fixtures don't represent real usage

**Fix**: Use actual production data from `inputs/` directory

---

#### Mistake 3: Not showing usage workflows

```markdown
Feature implemented
All tests pass
```

**Problem**: Doesn't demonstrate real workflows

**Fix**: Show searching, filtering, extracting - actual use cases

---

#### Mistake 4: No concrete results

```markdown
JSON loader works
Configuration functional
```

**Problem**: Vague, unverifiable claims

**Fix**: Provide file sizes, table counts, extracted data samples

---

#### Mistake 5: Not proving integration

```markdown
New loader implemented
Tests pass
```

**Problem**: Doesn't show downstream systems still work

**Fix**: Demonstrate existing search/filter/extract workflows function

---

### Evidence Quality Checklist

When reviewing PRs, verify the evidence demonstrates:

- **Real production data** - Not test fixtures, actual files with concrete sizes/results
- **Concrete outcomes** - Specific numbers, file names, measurable results
- **Integration proof** - Downstream workflows continue to function
- **End-to-end verification** - Feature works in full application context
- **Removal verification** (if applicable) - Old code cannot be imported
- **Configuration validation** (if applicable) - Defaults and overrides work

The inline examples throughout this document demonstrate the expected evidence quality standards.

---

## PR Review Process

### Review Stages

**1. Automated Checks** (must pass before human review):

- Tests: `just test`
- Coverage: 80%+ target (`just test-cov`)
- Pre-commit hooks: Automatically enforce linting, type checking, and formatting at commit level

**2. Human Review** (focuses on):

- Code quality and maintainability
- Functional evidence completeness
- Architecture alignment
- Security considerations

**3. Approval Requirements**:

- All automated checks pass
- At least one approving review
- No unresolved comments
- Functional evidence for all ACs

### Reviewer Responsibilities

**Check for**:

- [ ] PR title follows format: `TT-XXX: Description`
- [ ] Jira ticket linked in PR body
- [ ] Functional evidence for EACH acceptance criterion
- [ ] Evidence uses production data (not test fixtures)
- [ ] All quality gates passed (tests, types, linting)
- [ ] Changes aligned with ticket requirements
- [ ] No security vulnerabilities introduced
- [ ] Documentation updated if needed

**Provide feedback on**:

- Code quality and patterns
- Test coverage gaps
- Evidence completeness
- Integration concerns
- Performance considerations

---

## Merge Strategies

### Preferred Method: Squash and Merge

**Default for most PRs**:

- Creates single commit on main
- Keeps main branch history clean
- Commit message derived from PR title + body

**When to use**:

- Feature branches with multiple WIP commits
- Bug fixes with iterative changes
- Most standard PRs

### Alternative: Merge Commit

**Preserves branch history**:

- Creates merge commit
- All branch commits remain visible
- More detailed history

**When to use**:

- Large features with logical commit breakdown
- When commit history tells a story
- Rarely needed in most projects

### Alternative: Rebase and Merge

**Linear history**:

- Replays commits on main
- No merge commit created
- Clean, linear history

**When to use**:

- PRs with well-crafted, logical commits
- When individual commits should be preserved
- Usually overkill for most projects

### Merge Requirements

Before merging, verify:

- [ ] All checks passed (CI/CD green)
- [ ] At least one approval
- [ ] No merge conflicts
- [ ] Jira ticket status will update to "Done" (automated)
- [ ] Branch will be deleted after merge (automated)

---

## Integration with Jira

### Jira Ticket References

**In PR Titles**:

- Format: `TT-XXX: Description`
- Example: `TT-87: Migrate from GitHub Issues to Jira`

**In PR Bodies**:

- Link format: `[TT-XXX](https://mandeng.atlassian.net/browse/TT-XXX)`
- Include in "Related Jira Issue" section

**In Commit Messages**:

- Start with: `TT-XXX:`
- Example: `TT-87: Add Jira workflow agent configuration`

### Automated Status Transitions

**GitHub → Jira automation** (via `.github/workflows/jira-transition.yml`):

| GitHub Event | Jira Status Transition |
|--------------|------------------------|
| Branch created (via API) | To Do → In Progress |
| PR opened | In Progress → In Review |
| PR merged | In Review → Done |

**CRITICAL**: The "Branch created" event only triggers when branches are created via the GitHub API or UI. Creating a branch locally and pushing does NOT trigger this event. Always use the remote-first pattern (see [Git Workflow Patterns](#git-workflow-patterns)).

**Important**: Do NOT manually update Jira status - automation handles this.

### Workflow Example

1. Developer picks up Jira ticket TT-87 (status: To Do)
2. Create branch: `feature/TT-87-migrate-to-jira`
3. GitHub workflow → TT-87 moves to "In Progress"
4. Make commits: `TT-87: Add agent configs`
5. Push commits to remote
6. Create PR: `TT-87: Migrate from GitHub Issues to Jira`
7. GitHub workflow → TT-87 moves to "In Review"
8. Code review and approval
9. Merge PR to main
10. GitHub workflow → TT-87 moves to "Done"

---

## Git Workflow Patterns

### Starting New Work

**CRITICAL: Remote-First Branch Creation**

Branches MUST be created on remote FIRST using the GitHub API. This ensures the GitHub `create` event fires, which triggers the Jira automation (To Do → In Progress).

**Why Remote-First**: Creating a branch locally then pushing does NOT trigger GitHub's `create` event - it triggers a `push` event instead. The Jira automation workflow listens for `create` events, so local-first branch creation breaks the automation chain.

```bash
# 1. Ensure local main is up to date
git checkout main
git pull origin main

# 2. Get SHA for branch base
MAIN_SHA=$(git rev-parse main)

# 3. CRITICAL: Create branch on REMOTE FIRST via GitHub API
# This triggers the 'create' event which transitions Jira to "In Progress"
gh api repos/{owner}/{repo}/git/refs \
  -f ref="refs/heads/feature/TT-XXX-description" \
  -f sha="$MAIN_SHA"

# 4. Fetch and checkout the remote branch locally
git fetch origin
git checkout feature/TT-XXX-description

# 5. Make changes
# ... edit files ...

# 6. Stage and commit
git add .
git commit -m "TT-XXX: Add feature implementation

- First change
- Second change"

# 7. Push commits
git push origin feature/TT-XXX-description
```

**With Worktrees** (optional, for isolated workspaces):

```bash
# Steps 1-3 same as above (create on remote first)

# 4. Fetch and create worktree pointing to the remote branch
git fetch origin
git worktree add /tmp/workspace-TT-XXX origin/feature/TT-XXX-description

# 5. Work in the worktree
cd /tmp/workspace-TT-XXX
# ... make changes, commit, push ...
```

**Key Points**:
- The branch MUST exist on remote BEFORE any local checkout
- The GitHub API call triggers the `create` event
- This ensures Jira transitions from "To Do" to "In Progress"
- NEVER create a branch locally first

### Creating Pull Request

**After pushing branch**:

1. Navigate to GitHub repository
2. Click "New Pull Request"
3. Select base: `main`, compare: `feature/TT-87-migrate-to-jira`
4. Fill in PR title: `TT-87: Migrate from GitHub Issues to Jira`
5. Fill in PR body using template (see [PR Body Structure](#pr-body-structure))
6. Create PR

**Or via github-workflow agent** (delegated):

- Agent handles all mechanical PR creation steps
- Main agent provides context (ticket, evidence, changes)
- github-workflow agent formats and creates PR

### Updating PR After Review

```bash
# 1. Make requested changes
# ... edit files based on review feedback ...

# 2. Commit changes
git add .
git commit -m "TT-87: Address code review feedback

- Refactor validation logic per review
- Add additional test coverage
- Update docstrings"

# 3. Push updates
git push origin feature/TT-87-migrate-to-jira

# PR updates automatically
```

### Handling Merge Conflicts

```bash
# 1. Update main branch
git checkout main
git pull origin main

# 2. Switch back to feature branch
git checkout feature/TT-87-migrate-to-jira

# 3. Rebase on main
git rebase main

# 4. Resolve conflicts
# ... edit files to resolve conflicts ...

git add <resolved-files>
git rebase --continue

# 5. Force push (required after rebase)
git push --force-with-lease origin feature/TT-87-migrate-to-jira
```

---

## Response Formats

### Success Response (PR Created)

```
Created PR #45
Title: TT-87: Migrate from GitHub Issues to Jira
Branch: feature/TT-87-migrate-to-jira → main
URL: https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/pull/45
Status: Open, awaiting review
```

### Success Response (PR Merged)

```
Merged PR #45
Title: TT-87: Migrate from GitHub Issues to Jira
Method: Squash and merge
Status: Merged to main
Jira: TT-87 moved to "Done"
```

### Error Response (Cannot Create PR)

```
Cannot create PR
Reason: Branch feature/TT-87-migrate-to-jira does not exist
Need: Push commits to the branch first
Suggestion: Run 'git push -u origin feature/TT-87-migrate-to-jira'
```

### Error Response (Checks Failed)

```
Cannot merge PR #45
Reason: CI checks failing
Failed checks:
  - Type checking: 3 errors in src/document/loader.py
  - Tests (pytest): 2 failing tests
Need: Fix errors and push updated code
```

### Info Response (PR Status)

```
PR #45 Status
Title: TT-87: Migrate from GitHub Issues to Jira
Status: Open
Reviews: 1 approved, 0 changes requested
Checks: All passing
  - Type checking
  - Linting
  - Tests (pytest)
  - Coverage (85%)
Ready to merge: Yes
```

---

## Quality Gates

### Pre-PR Checklist

Before creating PR, verify:

- [ ] Branch name follows convention: `<type>/TT-XXX-description`
- [ ] All commits reference Jira ticket: `TT-XXX: ...`
- [ ] Code changes complete and tested
- [ ] All acceptance criteria met

### PR Creation Checklist

When creating PR, ensure:

- [ ] PR title follows format: `TT-XXX: Description`
- [ ] PR body includes all required sections
- [ ] Jira ticket linked with full URL
- [ ] Functional evidence for EACH acceptance criterion
- [ ] Evidence uses production/realistic data
- [ ] Test evidence included (types, linting, tests pass)
- [ ] Changes documented

### Pre-Merge Checklist

Before merging PR, verify:

- [ ] All CI/CD checks passed
- [ ] At least one approving review
- [ ] No unresolved review comments
- [ ] No merge conflicts
- [ ] Functional evidence reviewed and accepted
- [ ] Code quality meets standards
- [ ] No security vulnerabilities introduced

### Post-Merge Checklist

After merging PR, confirm:

- [ ] PR marked as merged
- [ ] Branch deleted (automated)
- [ ] Jira ticket moved to "Done" (automated)
- [ ] No broken functionality on main
- [ ] CI/CD passing on main branch

---

## Technical Standards

All PRs must meet these technical standards:

### Code Quality

- **Testing**: `just test` with 80%+ coverage (`just test-cov`)
- **Pre-commit Hooks**: Linting, type checking, and formatting enforced at commit level
- **Security**: No vulnerabilities (OWASP top 10)

### Documentation

- **Code Comments**: Complex logic explained
- **Docstrings**: All public functions/classes
- **README Updates**: If user-facing changes
- **CHANGELOG**: For notable changes (optional)

---

## Reference Documents

- **[ISSUES_SPEC.md](ISSUES_SPEC.md)** - Jira issue specifications
- **[PR_EVIDENCE_GUIDELINES.md](PR_EVIDENCE_GUIDELINES.md)** - Comprehensive evidence standards

---

## Evidence Standards Summary

This specification provides comprehensive inline examples throughout demonstrating:

- **Production data usage** - Real files, concrete sizes, measurable outcomes
- **Functional evidence** - Not just "tests pass", but actual usage workflows
- **Integration verification** - Downstream systems continue to function
- **Evidence by AC type** - Feature, removal, dependency, configuration, version upgrade
- **Common mistakes to avoid** - Test-only evidence, vague claims, missing integration proof

Refer to the detailed examples in the [Functional Evidence Requirements](#functional-evidence-requirements) section.

---

## Summary

This specification defines:

1. **Branch Naming**: Consistent conventions tied to Jira tickets
2. **Commit Format**: Structured messages with ticket references
3. **PR Standards**: Required sections and format
4. **Functional Evidence**: Production data verification for all ACs
5. **Review Process**: Automated and human review stages
6. **Merge Strategies**: Squash, merge commit, or rebase options
7. **Jira Integration**: Automated status transitions
8. **Git Workflows**: Standard patterns for common operations
9. **Quality Gates**: Pre-PR, creation, pre-merge, post-merge checklists
10. **Response Formats**: Consistent success/error messaging

**Implementation Note**: This is a specification document. The github-workflow agent determines the implementation mechanism (GitHub MCP tools, gh CLI, or other approaches) appropriate for the project.

All developers and agents must follow these specifications when working with GitHub operations.
