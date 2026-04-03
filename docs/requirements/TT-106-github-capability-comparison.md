# TT-106: GitHub MCP Migration — Capability Diff

> **Date:** 2026-04-03
> **Context:** Subagents adopt MCP via Bifrost. Skill scripts are retired.

---

## What MCP gains over skill scripts

MCP provides 26 tools. The 12 skill scripts covered only PR basics, branches, and CI. MCP adds:

- **PR reviews:** get reviews, get review comments, create review (approve/request changes), merge PR, update PR branch
- **Issues:** create, get, list, update, comment, search
- **Repository:** get file contents, create/update file, push multi-file commits, list commits, search code
- **Performance:** ~24% faster (231ms avg vs 306ms) due to persistent connection vs per-call `gh` process spawn

## What MCP doesn't cover yet

6 operations in the current skill scripts have no MCP equivalent:

| Operation | Current script | Workaround |
|-----------|---------------|------------|
| Edit PR title/body | `edit-pr.sh` | Agent uses `gh pr edit` via Bash |
| List branches | `list-branches.sh` | Agent uses `gh api` via Bash |
| Delete branch | `delete-branch.sh` | Agent uses `gh api` via Bash |
| List workflow runs | `list-workflow-runs.sh` | Agent uses `gh run list` via Bash |
| Get workflow run | `get-workflow-run.sh` | Agent uses `gh run view` via Bash |
| Rerun workflow | `rerun-workflow.sh` | Agent uses `gh run rerun` via Bash |

The subagent has Bash. For these 6 operations it calls `gh` directly — no script wrapper needed. As the upstream GitHub MCP server adds tools, the workarounds drop away.

## PR comment note

`add-pr-comment.sh` uses `gh pr comment`. MCP has `github-add_issue_comment` which works on the same number (PRs are issues). Functionally equivalent for top-level comments.

## Performance

| Operation | Skill (avg) | MCP (avg) |
|-----------|---:|---:|
| List open PRs | 234 ms | 226 ms |
| Get PR #137 | 414 ms | 247 ms |
| Get PR files | 270 ms | 220 ms |

Both sub-500ms. Negligible vs LLM inference time.
