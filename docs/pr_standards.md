# Pull Request Standards

This document contains detailed PR evidence templates, quality gates, and checklists.
See [CLAUDE.md](../CLAUDE.md) for the mandatory rules (kept inline there for agent visibility).

---

## Functional Testing Requirement

**Unit tests are NOT actual tests. You MUST functionally test all code changes before creating a PR.**

Before creating any pull request, you MUST:

1. **Actually run the code** in a realistic environment
2. **Verify the feature works** by exercising it manually or via integration
3. **Capture evidence** (logs, output, screenshots) proving it works
4. **Document blockers** if testing is not possible (missing tools, services, etc.)

**If you cannot test a feature:**
- STOP and notify the user
- Explain what is missing (redis-cli, API credentials, external service, etc.)
- Do NOT create a PR with untested code

---

## What Unit Tests Do NOT Prove

Passing unit tests means:

- **NOT** that the feature works
- **NOT** that integration points function
- **NOT** that the code behaves correctly in production
- **ONLY** that the code compiles and isolated units behave as mocked

---

## Evidence: Insufficient vs Required

### Insufficient: Test-only evidence

```
## Test Evidence
- test_load_json PASSED
- All 50 unit tests pass
- mypy passes
- ruff passes
```

These are quality gates, NOT functional evidence.

### Required: Functional evidence with production data

```
## Functional Evidence

### AC1: [Specific acceptance criterion from the Jira ticket]

**Real Example: [Demonstrating the feature with realistic data]**

```python
# Code showing feature working with production/realistic data
# Include concrete, measurable results
```

**Results:**
- Specific outcome 1 with concrete details
- Specific outcome 2 with measurable results
```

---

## Evidence Standards

For EVERY acceptance criterion, provide:

### 1. Real Production/Realistic Data

- Use actual production data or realistic files (NOT test fixtures from `unit_tests/fixtures/`)
- For file-based features: show file names, sizes, and processing results
- For API/service features: show realistic requests/responses
- For UI features: show actual user workflows with real data

### 2. Actual Usage Workflows

- Demonstrate the feature working as specified in acceptance criteria
- Show integration with existing systems works
- Prove end-to-end workflows function correctly

### 3. Concrete, Measurable Results

- Specific file names, sizes, or identifiers
- Quantifiable outcomes (counts, durations, sizes)
- Sample output data relevant to the feature

### 4. End-to-End Verification

- Show feature works in application context
- Verify dependencies actually work (import and use them)
- Demonstrate configuration settings function

---

## PR Body Required Sections

Every PR body MUST contain these sections:

| Section | Description |
|---------|-------------|
| **Summary** | 1-3 bullet points describing what was done |
| **Related Jira Issue** | Clickable link to TT-XXX |
| **Acceptance Criteria** | Each AC with functional evidence |
| **Test Evidence** | Quality gate results (tests, mypy, ruff) |
| **Changes Made** | List of files/modules changed |

---

## PR Quality Assurance Checklist

After creating or updating any PR, the github-workflow agent MUST:

1. **Re-read the PR** to verify it was created correctly
2. **Check completeness** against required sections:
   - Summary section present and meaningful
   - Related Jira Issue with clickable link
   - Acceptance Criteria with evidence for EACH AC
   - Test Evidence section
   - Changes Made section
3. **Fix any deficiencies** before reporting back
4. **Report confidence level** (✅ Complete or ⚠️ Needs attention)
