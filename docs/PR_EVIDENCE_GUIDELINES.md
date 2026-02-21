# Pull Request Evidence Guidelines

> **Principle:** Test Evidence ≠ Functional Evidence
>
> Unit tests passing is necessary but NOT sufficient to demonstrate acceptance criteria are met.

## Overview

When creating a Pull Request, you must provide **functional evidence** that demonstrates each acceptance criterion is satisfied through **real usage examples**, not just test results.

## Why This Matters

**Problem:** "All tests pass ✓" doesn't prove the feature works in production.

**Solution:** Show the feature working with real data, real workflows, and real usage patterns.

---

## Evidence Standards

### ❌ Insufficient Evidence

```markdown
## Test Evidence

### AC1: Feature successfully processes data
- ✅ test_process_data_success PASSED
- ✅ test_process_file_not_found PASSED

### AC2: All unit tests pass
```bash
$ pytest tests/
======================== 50 passed ========================
```
```

**Why insufficient:**
- Doesn't show the feature actually works with production data
- Only proves test fixtures pass
- No demonstration of real-world usage
- No proof downstream workflows work

---

### ✅ Sufficient Evidence

```markdown
## Functional Evidence

### AC1: [Your specific acceptance criterion]

**Real Example: [Demonstrating the feature with realistic data]**

```python
# Code showing the feature working with production/realistic data
# Include concrete, measurable results
```

**Results:**
- ✓ [Specific outcome with measurable details]
- ✓ [File names, sizes, counts - whatever is relevant]
- ✓ [Sample output showing it works]
```

**Why sufficient:**
- Shows feature works with REAL production/realistic data
- Demonstrates ACTUAL usage patterns relevant to the feature
- Proves functionality meets acceptance criteria
- Provides concrete examples anyone can verify

---

## Evidence Requirements by Acceptance Criteria Type

### 1. Feature Functionality

**Generic Requirements:**
- ✅ Demonstrate with REAL production/realistic data (not test fixtures)
- ✅ Show concrete, measurable results relevant to the feature
- ✅ Display sample output that proves it works
- ✅ Verify data/results are correct and usable

**How to apply this:**
- For file processing: show file names, sizes, processing results
- For API endpoints: show request/response with realistic data
- For UI features: show workflows with actual user data
- For configurations: show settings applied with real values

---

### 2. Code Removal

**Required Evidence:**
- ✅ Prove old modules cannot be imported
- ✅ Show what modules ARE available
- ✅ Verify file structure confirms deletion

---

### 3. Dependency Changes

**Required Evidence:**
- ✅ Prove dependency cannot be imported (if removed)
- ✅ Show it's not in pyproject.toml
- ✅ Verify lock file doesn't include it
- ✅ Demonstrate alternative works (if replaced)

---

### 4. Configuration Settings

**Required Evidence:**
- ✅ Show default value works
- ✅ Demonstrate override via environment variable
- ✅ Prove it's actually used in the application
- ✅ Test with realistic values

---

### 5. Version Upgrades

**Required Evidence:**
- ✅ Show actual version running
- ✅ Run real application code (not just tests)
- ✅ Verify all dependencies compatible
- ✅ Demonstrate production workloads succeed

---

### 6. Integration/Compatibility

**Generic Requirements:**
- ✅ Show the feature integrates with existing systems
- ✅ Demonstrate workflows continue to function
- ✅ Verify all necessary interfaces/fields exist
- ✅ Prove no regressions in dependent functionality

---

## PR Description Template

Use this template structure for PR descriptions:

```markdown
## Summary
[Brief description of changes]

## Related Jira Issue
**Jira**: [TT-XXX](https://mandeng.atlassian.net/browse/TT-XXX)

## Acceptance Criteria - Functional Evidence

### ✅ AC1: [Criterion Title]

**Real Example: [Specific usage scenario]**

```[language]
[Actual code demonstrating the feature]
```

**Results:**
- ✓ [Concrete outcome 1]
- ✓ [Concrete outcome 2]

**Production Data Tested:**
- [File 1]: [size] → [results]
- [File 2]: [size] → [results]

---

### ✅ AC2: [Next Criterion]

[Repeat pattern...]

---

## Test Evidence

- ✅ All tests passing
- ✅ Coverage: [X]% (target: 80%+)
- ✅ Type checking clean
- ✅ Linting clean

## Changes Made

- [File/module 1]: [What was changed and why]
- [File/module 2]: [What was changed and why]
```

---

## Quick Checklist

Before submitting your PR, verify you have:

- [ ] Demonstrated each AC with **real production data** (not fixtures)
- [ ] Shown **actual usage patterns** (not just "tests pass")
- [ ] Proved **downstream workflows** still function
- [ ] Used **concrete examples** anyone can verify
- [ ] Provided **file names, sizes, and results** for production data tested
- [ ] Showed **real commands** and their **actual output**
- [ ] Demonstrated feature works **end-to-end** in application context

---

## Common Mistakes to Avoid

### ❌ Mistake 1: Only showing test results
```markdown
✅ test_load_json PASSED
✅ test_extract_tables PASSED
```
**Fix:** Show loading real production files, not test fixtures.

---

### ❌ Mistake 2: Using sample/mock data
```markdown
tables = await loader.load('tests/fixtures/sample.json')
✓ Loaded 2 tables
```
**Fix:** Use actual production data.

---

### ❌ Mistake 3: Not showing usage workflows
```markdown
✅ Feature implemented
✅ All tests pass
```
**Fix:** Demonstrate searching, filtering, extracting - real workflows.

---

### ❌ Mistake 4: No concrete results
```markdown
✅ Feature works
✅ Configuration functional
```
**Fix:** Show actual file sizes, counts, extracted data samples.

---

## Questions?

- **Q: Do I still need to run tests?**
  - A: YES! Tests must pass. But passing tests alone are not evidence of acceptance criteria.

- **Q: What if production data doesn't exist yet?**
  - A: Create realistic production-like data, not simple fixtures. Document what real data will look like.

- **Q: How much evidence is enough?**
  - A: Each acceptance criterion needs at least one concrete example with real data showing it works.

- **Q: Can I use multiple examples?**
  - A: Absolutely! 2-3 production examples per AC is ideal.

---

## References

- [CLAUDE.md](../CLAUDE.md) - Project-level agent instructions
- [GITHUB_WORKFLOW_SPEC.md](./GITHUB_WORKFLOW_SPEC.md) - GitHub workflow standards
- [PR_EVIDENCE_CHECKLIST.md](./PR_EVIDENCE_CHECKLIST.md) - Quick reference checklist
