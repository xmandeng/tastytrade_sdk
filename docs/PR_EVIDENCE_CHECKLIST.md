# PR Evidence Checklist

> **Quick Reference:** Use this checklist before submitting any PR.

## The Core Rule

**Test Evidence ≠ Functional Evidence**

Unit tests passing is **necessary** but **NOT sufficient**. You must demonstrate each acceptance criterion with real production data.

---

## Before Submitting PR

### ✅ For EACH Acceptance Criterion

- [ ] **Used REAL production/realistic data**
  - NOT test fixtures from `tests/fixtures/`
  - For file-based features: show file names and sizes
  - For other features: use realistic data appropriate to the feature

- [ ] **Showed concrete, measurable results**
  - Quantifiable outcomes (counts, sizes, durations)
  - Sample output relevant to the feature
  - NOT just "it works" or "tests pass"

- [ ] **Demonstrated feature working as specified**
  - Actual usage appropriate to the acceptance criteria
  - Integration with existing systems
  - Show the feature functioning in realistic context

- [ ] **Provided end-to-end verification**
  - Feature works in application context
  - Dependencies actually work (import and use them)
  - Configuration settings function

### ✅ Test Evidence (Also Required)

- [ ] All tests pass
- [ ] Type checking clean
- [ ] Linting clean

---

## PR Description Must Include

```markdown
## Acceptance Criteria - Functional Evidence

### ✅ AC1: [Criterion Title]

**Real Example: [Demonstrating the feature]**
```python
# Code showing feature working with production/realistic data
result = await feature.execute('inputs/realistic_data.json')
print(f"Processed {result.count} items")  # Concrete, measurable result
```

**Results:**
- ✓ [Specific outcome with measurable details]
- ✓ [File names, sizes, counts - whatever is relevant to your feature]
- ✓ [Sample output showing it works]

**Data/Resources Tested:**
- [List what you actually tested with concrete details]
```

---

## Common Mistakes

### ❌ Insufficient

```markdown
## Evidence
- ✅ test_load_json PASSED
- ✅ 50 tests passed
- ✅ Type checking passed
```

**Why:** Only shows tests pass, not that feature works.

---

### ✅ Sufficient

```markdown
## Functional Evidence

### AC1: [Your acceptance criterion]

**Real Example:**
```python
result = await feature.process('inputs/realistic_data.json')
# Result: Processed 25 items
print(f"Success: {result.status}")
# Output: Success: completed
```

**Results:**
- ✓ [Specific data/file used with size/details]
- ✓ [Measurable outcome with numbers]
- ✓ [Key outputs demonstrating it works]
```

**Why:** Shows feature working with realistic data, concrete results relevant to the acceptance criteria.

---

## Quick Validation

Run this before creating PR:

```bash
# 1. Verify feature with realistic data (adapt to your feature)
# Write code to demonstrate your feature working
# Use realistic data appropriate to your acceptance criteria
# Show concrete, measurable results

# 2. Run tests
# Use your project's test command

# 3. Type check
# Use your project's type checker

# 4. Lint
# Use your project's linter
```

---

## Resources

- **Comprehensive Guide:** [docs/PR_EVIDENCE_GUIDELINES.md](./PR_EVIDENCE_GUIDELINES.md)
- **Agent Instructions:** [CLAUDE.md](../CLAUDE.md)

---

## Questions?

**Q: Do I need both functional evidence AND test results?**
A: YES. Tests verify code correctness. Functional evidence verifies acceptance criteria are met.

**Q: Can I use test fixtures?**
A: NOT for evidence. Use realistic data appropriate to your feature.

**Q: How much is enough?**
A: Each AC needs at least one concrete example with realistic data. 2-3 examples is ideal.

**Q: What if realistic data doesn't exist yet?**
A: Create realistic production-like data. Document what real data will look like and why your test data is representative.

---

## Remember

Before clicking "Create Pull Request":

1. ✅ Read EACH acceptance criterion
2. ✅ Test with realistic data appropriate to EACH criterion
3. ✅ Document concrete, measurable results
4. ✅ Show feature working as specified
5. ✅ Capture concrete output
6. ✅ Include in PR description

**If you can't check all boxes above, your PR is not ready.**
