# Claude Code Persistence Setup for DevContainer

This document outlines the steps taken to configure persistent Claude Code sessions across devcontainer rebuilds.

## Problem
Claude Code loses authentication and conversation context when devcontainers are rebuilt, requiring re-authentication and losing all prior context.

## Solution
Mount the Claude Code configuration directory from the host filesystem to persist across container rebuilds.

## Implementation Steps

### 1. DevContainer Mount Configuration
In `.devcontainer/devcontainer.json`, ensure the following mount is configured:

```json
"mounts": [
  "source=${localEnv:HOME}/.ssh,target=/home/vscode/.ssh,type=bind,consistency=cached",
  "source=${localEnv:HOME}/.claude,target=/home/vscode/.claude,type=bind,consistency=cached"
]
```

### 2. Setup Script Enhancement
In `.devcontainer/setup.sh`, add the following section after the initial setup:

```bash
# Ensure Claude Code configuration directory exists and has proper permissions
if [ -d "/home/vscode/.claude" ]; then
    echo "Claude Code configuration directory found, ensuring proper permissions..."
    chmod 700 /home/vscode/.claude
    # Ensure credentials file has proper permissions if it exists
    if [ -f "/home/vscode/.claude/.credentials.json" ]; then
        chmod 600 /home/vscode/.claude/.credentials.json
    fi
else
    echo "Note: Claude Code configuration directory will be created on first login"
fi
```

## What Gets Persisted

The `~/.claude` directory contains:
- `.credentials.json` - Authentication tokens
- `projects/` - Project-specific contexts and conversations
- `shell-snapshots/` - Command history and shell state
- `todos/` - Task lists and project management data
- `statsig/` - Usage analytics
- `ide/` - IDE integration settings

## Verification Steps

After rebuilding the devcontainer:
1. Check that `ls ~/.claude` shows existing files
2. Claude Code should not require re-authentication
3. Previous conversation contexts should be available
4. Project-specific settings should be preserved

## Troubleshooting

If persistence fails:
1. Verify the host `~/.claude` directory exists and has proper permissions
2. Check devcontainer mount syntax in `devcontainer.json`
3. Ensure the devcontainer rebuild picks up the new configuration
4. Verify the setup script runs successfully during container creation

## Security Notes
- The `.claude` directory contains sensitive authentication data
- Proper file permissions (700 for directory, 600 for credentials) are enforced
- The mount uses `consistency=cached` for performance while maintaining data integrity
