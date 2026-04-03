# TT-106: Bifrost Validation Findings

**Date:** 2026-04-03
**Status:** Gate validation PASSED
**Source:** Bifrost docs, GitHub repo, Docker Hub, live testing

---

## Spec Mismatches

The design spec (v1.3) made assumptions about Bifrost that don't match the actual implementation. These are corrected below.

### 1. Docker Image Registry

| Spec | Actual |
|------|--------|
| `ghcr.io/maximhq/bifrost:latest` | `maximhq/bifrost:latest` (Docker Hub) |

The image is on Docker Hub, not GitHub Container Registry.

### 2. Config File Path

| Spec | Actual |
|------|--------|
| `/etc/bifrost/config.json` | `/app/data/config.json` |

Bifrost expects config at `/app/data/config.json` in Docker. Set via `-app-dir` flag or volume mount to `/app/data`.

### 3. Config Structure

The spec showed a flat array of server configs. The actual format wraps configs under `mcp.client_configs`:

```json
{
  "mcp": {
    "client_configs": [
      {
        "name": "github",
        "connection_type": "stdio",
        "stdio_config": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-github"],
          "envs": ["GITHUB_PERSONAL_ACCESS_TOKEN"]
        },
        "is_ping_available": true,
        "tools_to_execute": ["*"]
      }
    ]
  }
}
```

Additional fields not in the spec: `is_ping_available`, `tools_to_auto_execute`, `auth_type`, `tool_sync_interval`.

### 4. Tool Namespacing Separator

| Spec | Actual |
|------|--------|
| `mcp__github__create_issue` (double underscore) | `github-create_issue` (hyphen) |

Bifrost uses `clientName-toolName` with a **hyphen** separator. The `name` field in the client config becomes the prefix. This is different from Claude Code's `mcp__server__tool` convention.

**Impact:** All tool references in subagent definitions, curl calls, and the generator script must use the hyphen format.

### 5. Default Port

Bifrost defaults to port **8080**. Overridable via `APP_PORT` env var or `-port` CLI flag. We map this to external ports (3001, 3002) in docker-compose.

### 6. Health Endpoint

Confirmed: `GET /health` returns `200 OK` with `{"status": "ok", ...}` when healthy, `503` when not.

The healthcheck in docs uses `wget` not `curl`:
```yaml
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "-O", "/dev/null",
         "http://localhost:8080/health"]
```

### 7. MCP Endpoint

Confirmed: `POST /mcp` accepts JSON-RPC 2.0 messages including `tools/list` and `tools/call`. `GET /mcp` provides SSE transport.

### 8. `envs` Field

The `envs` field is an array of environment variable **names** to pass through from the host (e.g., `["GITHUB_PERSONAL_ACCESS_TOKEN"]`), not key-value pairs. Bifrost reads the named variables from its own environment and passes them to the STDIO process.

---

## Credentials Mapping

Available credentials in `.env` and the env var names the MCP servers expect:

| MCP Server | Env Var in `.env` | Env Var MCP Server Expects | Notes |
|------------|-------------------|---------------------------|-------|
| GitHub | `GITHUB_PERSONAL_ACCESS_TOKEN` | `GITHUB_PERSONAL_ACCESS_TOKEN` | Direct match |
| Atlassian | `ATLASSIAN_USER_EMAIL`, `ATLASSIAN_API_TOKEN`, `ATLASSIAN_SITE_NAME` | TBD — depends on MCP server package | Need to verify package and its expected env vars |

---

## Corrected Implementation Plan

### Dockerfile (dev cluster)

```dockerfile
FROM maximhq/bifrost:latest

# Install Node.js runtime for STDIO MCP servers
RUN apt-get update && apt-get install -y nodejs npm && \
    npm install -g npx

# Pre-cache MCP server packages
RUN npx -y @modelcontextprotocol/server-github --help || true

COPY bifrost-config.json /app/data/config.json
```

### docker-compose service

```yaml
bifrost-dev:
  build: ./docker/bifrost-dev
  ports:
    - "3001:8080"
  environment:
    - GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PERSONAL_ACCESS_TOKEN}
  healthcheck:
    test: ["CMD", "wget", "--no-verbose", "--tries=1", "-O", "/dev/null",
           "http://localhost:8080/health"]
    interval: 10s
    timeout: 5s
    retries: 3
    start_period: 10s
  networks:
    - internal_net
```

Note: Internal port is 8080 (Bifrost default), mapped to 3001 externally.

---

## Gate Validation Results (2026-04-03)

**PASSED.** Bifrost STDIO proxying of GitHub MCP server confirmed working.

### Test Environment

- Image: `maximhq/bifrost:latest` (Alpine 3.23, Go binary)
- Node.js: 24.14.1 (installed via `apk add nodejs npm`)
- MCP server: `@modelcontextprotocol/server-github`
- Credential: `GITHUB_PERSONAL_ACCESS_TOKEN` (passed through via `envs` array)
- Port mapping: 3001 (host) → 8080 (container)

### `tools/list` Result

26 tools returned, all namespaced as `github-<tool_name>`:

```
github-add_issue_comment
github-create_branch
github-create_issue
github-create_or_update_file
github-create_pull_request
github-create_pull_request_review
github-create_repository
github-fork_repository
github-get_file_contents
github-get_issue
github-get_pull_request
github-get_pull_request_comments
github-get_pull_request_files
github-get_pull_request_reviews
github-get_pull_request_status
github-list_commits
github-list_issues
github-list_pull_requests
github-merge_pull_request
github-push_files
github-search_code
github-search_issues
github-search_repositories
github-search_users
github-update_issue
github-update_pull_request_branch
```

### `tools/call` Result

Called `github-list_pull_requests` with `{"owner":"xmandeng","repo":"tastytrade_sdk","state":"open","per_page":3}`. Returned real PR data from the GitHub API including PR #137 (TT-78).

### Resolved Open Questions

1. **Bifrost base image OS** — Alpine Linux 3.23. Uses `apk` not `apt-get`. Runs as `appuser` (UID 1000) — Dockerfile must `USER root` before installing packages, then `USER appuser` after.
2. **GitHub MCP env var name** — `GITHUB_PERSONAL_ACCESS_TOKEN` works. The existing `.env` value is used directly.
3. **Atlassian MCP package** — Still to be verified in next phase.
