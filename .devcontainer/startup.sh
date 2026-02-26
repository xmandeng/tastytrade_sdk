#!/bin/bash
# DevContainer startup script - Loads .env and configures environment
#
# Runs on BOTH postCreateCommand (via setup.sh) and postStartCommand (container restart).
# All functions are idempotent — safe to re-run.

set -e

# Ensure UV is available in PATH
export PATH="$HOME/.local/bin:$PATH"

# ============================================================================
# FUNCTIONS
# ============================================================================

# Load and export .env file variables into the current environment
load_env_file() {
    local env_file="/workspace/.env"

    if [ ! -f "$env_file" ]; then
        echo "WARNING: .env file not found at $env_file"
        return 1
    fi

    echo "Loading environment variables from .env..."

    # Read .env file and export variables
    while IFS='=' read -r key value || [ -n "$key" ]; do
        # Skip comments, empty lines, and lines without =
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        [[ ! "$key" =~ = ]] && [[ -z "$value" ]] && continue

        # Trim whitespace from key
        key=$(echo "$key" | xargs)

        # Remove surrounding quotes from value if present
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"

        # Export the variable to current environment
        export "$key=$value"
        echo "  Loaded: $key"
    done < "$env_file"

    return 0
}

# Persist environment variables to /etc/environment (for non-interactive processes like MCP servers)
persist_env_to_system() {
    local env_file="/etc/environment"

    # Check if variables are already persisted
    if grep -q "^ATLASSIAN_SITE_NAME=" "$env_file" 2>/dev/null; then
        echo "Environment variables already persisted to /etc/environment"
        return 0
    fi

    echo "Persisting environment variables to /etc/environment (for MCP servers)..."

    # Backup original /etc/environment
    sudo cp "$env_file" "${env_file}.backup" 2>/dev/null || true

    # Add variables to /etc/environment (format: VAR=value, no export keyword)
    for var in GH_TOKEN GITHUB_PERSONAL_ACCESS_TOKEN ANTHROPIC_API_KEY OPENAI_API_KEY PYDANTIC_LOGFIRE_TOKEN ATLASSIAN_SITE_NAME ATLASSIAN_USER_EMAIL ATLASSIAN_API_TOKEN CC_LANGSMITH_API_KEY CC_LANGSMITH_PROJECT CC_LANGSMITH_DEBUG TRACE_TO_LANGSMITH; do
        if [ -n "${!var}" ]; then
            # Check if already exists
            if ! grep -q "^${var}=" "$env_file" 2>/dev/null; then
                echo "${var}=\"${!var}\"" | sudo tee -a "$env_file" > /dev/null
                echo "  Persisted: ${var}"
            fi
        else
            echo "  Skipped: ${var} (not set)"
        fi
    done

    # Also add JIRA_* aliases for Atlassian MCP server compatibility
    if [ -n "${ATLASSIAN_SITE_NAME}" ]; then
        if ! grep -q "^JIRA_URL=" "$env_file" 2>/dev/null; then
            echo "JIRA_URL=\"${ATLASSIAN_SITE_NAME}\"" | sudo tee -a "$env_file" > /dev/null
            echo "  Persisted: JIRA_URL (from ATLASSIAN_SITE_NAME)"
        fi
    fi
    if [ -n "${ATLASSIAN_USER_EMAIL}" ]; then
        if ! grep -q "^JIRA_USERNAME=" "$env_file" 2>/dev/null; then
            echo "JIRA_USERNAME=\"${ATLASSIAN_USER_EMAIL}\"" | sudo tee -a "$env_file" > /dev/null
            echo "  Persisted: JIRA_USERNAME (from ATLASSIAN_USER_EMAIL)"
        fi
    fi
    if [ -n "${ATLASSIAN_API_TOKEN}" ]; then
        if ! grep -q "^JIRA_API_TOKEN=" "$env_file" 2>/dev/null; then
            echo "JIRA_API_TOKEN=\"${ATLASSIAN_API_TOKEN}\"" | sudo tee -a "$env_file" > /dev/null
            echo "  Persisted: JIRA_API_TOKEN (from ATLASSIAN_API_TOKEN)"
        fi
    fi
}

# Persist environment variables to bashrc for interactive shells
persist_env_to_bashrc() {
    local bashrc="/home/developer/.bashrc"
    local marker="# Application Environment Variables (loaded from .env at container startup)"

    # Check if variables are already persisted
    if grep -q "^export GH_TOKEN=" "$bashrc" 2>/dev/null; then
        echo "Environment variables already persisted to .bashrc"
        return 0
    fi

    echo "Persisting environment variables to .bashrc..."

    # Ensure marker exists
    if ! grep -q "$marker" "$bashrc" 2>/dev/null; then
        echo '' >> "$bashrc"
        echo "$marker" >> "$bashrc"
    fi

    # Get line number of marker
    local marker_line=$(grep -n "$marker" "$bashrc" | cut -d: -f1)

    # Export application-specific variables right after marker
    for var in GH_TOKEN ANTHROPIC_API_KEY OPENAI_API_KEY PYDANTIC_LOGFIRE_TOKEN ATLASSIAN_SITE_NAME ATLASSIAN_USER_EMAIL ATLASSIAN_API_TOKEN CC_LANGSMITH_API_KEY CC_LANGSMITH_PROJECT CC_LANGSMITH_DEBUG TRACE_TO_LANGSMITH; do
        if [ -n "${!var}" ]; then
            # Check if already exists
            if ! grep -q "^export ${var}=" "$bashrc"; then
                # Insert after marker line
                sed -i "${marker_line}a export ${var}=\"${!var}\"" "$bashrc"
                marker_line=$((marker_line + 1))
                echo "  Persisted: ${var}"
            fi
        else
            echo "  Skipped: ${var} (not set)"
        fi
    done
}

# Configure git safely
configure_git() {
    echo "Configuring git..."

    # Set safe directory for the workspace
    git config --global --add safe.directory /workspace 2>/dev/null || true

    # Copy host gitconfig if available and not already done
    if [ -f /home/developer/.gitconfig-host ] && [ ! -f /home/developer/.gitconfig ]; then
        cp /home/developer/.gitconfig-host /home/developer/.gitconfig
        git config --global --add safe.directory /workspace 2>/dev/null || true
    fi

    # Configure user info if not set
    if ! git config --global user.name > /dev/null 2>&1; then
        git config --global user.name "Developer" 2>/dev/null || true
    fi

    if ! git config --global user.email > /dev/null 2>&1; then
        git config --global user.email "developer@localhost" 2>/dev/null || true
    fi

    echo "  Git configured"
}

# Configure GitHub CLI with token
configure_github_cli() {
    if [ -z "${GH_TOKEN}" ]; then
        echo "WARNING: No GitHub token found, skipping gh CLI configuration"
        return 0
    fi

    echo "Configuring GitHub CLI..."

    if ! command -v gh > /dev/null 2>&1; then
        echo "  gh CLI not found, skipping"
        return 0
    fi

    # Authenticate gh with token
    echo "$GH_TOKEN" | gh auth login --with-token 2>/dev/null || true

    # Setup git credential helper
    gh auth setup-git 2>/dev/null || true

    # Verify authentication
    if gh auth status >/dev/null 2>&1; then
        local gh_user=$(gh api user -q .login 2>/dev/null || echo 'unknown')
        echo "  GitHub CLI authenticated as: $gh_user"
    else
        echo "  GitHub CLI authentication may have failed"
    fi
}

# Add convenience aliases
add_convenience_aliases() {
    local bashrc="/home/developer/.bashrc"
    local bash_aliases="/home/developer/.bash_aliases"
    local profile="/home/developer/.profile"

    # Ensure PATH includes local bin (for claude, uv, etc.)
    if ! grep -q 'export PATH="\$HOME/.local/bin' "$bashrc" 2>/dev/null; then
        echo '' >> "$bashrc"
        echo '# Ensure local bin is in PATH (claude, uv, etc.)' >> "$bashrc"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$bashrc"
        echo "  Added PATH to .bashrc"
    fi

    # Create .bash_aliases file for aliases
    if [ ! -f "$bash_aliases" ]; then
        cat > "$bash_aliases" << 'EOF'
# Convenience aliases for development
alias claudeyolo="claude --dangerously-skip-permissions"
EOF
        echo "  Created .bash_aliases with convenience aliases"
    else
        # Add claudeyolo alias if missing
        if ! grep -q 'alias claudeyolo=' "$bash_aliases" 2>/dev/null; then
            echo 'alias claudeyolo="claude --dangerously-skip-permissions"' >> "$bash_aliases"
            echo "  Added claudeyolo alias"
        fi
    fi

    # Ensure .bashrc sources .bash_aliases (for interactive non-login shells)
    if ! grep -q "source.*\.bash_aliases\|\..*\.bash_aliases" "$bashrc" 2>/dev/null; then
        echo '' >> "$bashrc"
        echo '# Source aliases' >> "$bashrc"
        echo 'if [ -f ~/.bash_aliases ]; then' >> "$bashrc"
        echo '    . ~/.bash_aliases' >> "$bashrc"
        echo 'fi' >> "$bashrc"
        echo "  Configured .bashrc to source .bash_aliases"
    fi

    # Ensure .profile sources .bash_aliases (for login shells)
    # This is needed because .bashrc may exit early due to non-interactive check
    if [ -f "$profile" ] && ! grep -q "source.*\.bash_aliases\|\..*\.bash_aliases" "$profile" 2>/dev/null; then
        echo '' >> "$profile"
        echo '# Source aliases for login shells (in case .bashrc exited early)' >> "$profile"
        echo 'if [ -f "$HOME/.bash_aliases" ]; then' >> "$profile"
        echo '    . "$HOME/.bash_aliases"' >> "$profile"
        echo 'fi' >> "$profile"
        echo "  Configured .profile to source .bash_aliases"
    fi
}

# Create symlinks so Claude plugin paths from host resolve in container
# Claude Code writes absolute paths (with $HOME) into plugin config files.
# When $HOME differs between host and container, those paths break.
# This creates a symlink so paths written on the host still resolve here.
fix_claude_plugin_paths() {
    if [ -z "$HOST_HOME" ] || [ "$HOST_HOME" = "$HOME" ]; then
        echo "  No HOST_HOME mismatch, skipping"
        return 0
    fi

    echo "Creating symlink for Claude plugin path compatibility..."
    if [ -d "$HOME/.claude" ] && [ ! -e "$HOST_HOME/.claude" ]; then
        sudo mkdir -p "$HOST_HOME"
        sudo ln -sfn "$HOME/.claude" "$HOST_HOME/.claude"
        echo "  Linked $HOST_HOME/.claude -> $HOME/.claude"
    elif [ -L "$HOST_HOME/.claude" ]; then
        echo "  Symlink already exists at $HOST_HOME/.claude"
    else
        echo "  Skipped: $HOST_HOME/.claude already exists"
    fi
}

# Fix Docker socket permissions for Docker-from-Docker
fix_docker_socket_permissions() {
    if [ ! -S /var/run/docker.sock ]; then
        echo "  Docker socket not found, skipping Docker-from-Docker setup"
        return 0
    fi

    echo "Configuring Docker-from-Docker..."

    # Get the GID of the docker socket from the host
    local host_docker_gid=$(stat -c '%g' /var/run/docker.sock 2>/dev/null)

    if [ -z "$host_docker_gid" ]; then
        echo "  Unable to determine docker socket GID (non-critical, continuing)"
        return 0
    fi

    # Check if the docker group needs to be updated to match the host GID
    local container_docker_gid=$(getent group docker | cut -d: -f3 2>/dev/null || echo "")

    if [ "$container_docker_gid" != "$host_docker_gid" ]; then
        echo "  Adjusting docker group GID from $container_docker_gid to $host_docker_gid"
        sudo groupmod -g "$host_docker_gid" docker 2>/dev/null || true
        # Re-add developer user to ensure membership
        sudo usermod -aG docker developer 2>/dev/null || true
    fi

    # Make Docker socket accessible to all users (required for MCP servers)
    # MCP server processes spawned by Claude Code don't inherit group memberships properly
    sudo chmod 666 /var/run/docker.sock 2>/dev/null || true

    # Verify docker command works
    if docker ps >/dev/null 2>&1; then
        echo "  Docker-from-Docker configured successfully"
        docker version --format '  Docker version: {{.Client.Version}}' 2>/dev/null || true
    else
        echo "  Docker command available but may not be working"
    fi
}

# Initialize quber-workflow (generates Claude settings, hooks, skills)
initialize_quber_workflow() {
    echo "Initializing quber-workflow..."

    if ! command -v uv > /dev/null 2>&1; then
        echo "  uv not found, skipping quber-workflow init"
        return 0
    fi

    cd /workspace
    if uv run quber-workflow init --config /workspace/.devcontainer/quber-workflow.yaml; then
        echo "  quber-workflow initialized successfully"
    else
        echo "  quber-workflow init failed (non-critical, continuing)"
    fi
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

echo "==============================================="
echo "  DevContainer Startup Configuration"
echo "  Project: tastytrade-sdk"
echo "==============================================="
echo ""

# Step 1: Ensure Python virtual environment exists
# This must run early so VS Code extensions (Ruff, Pylance) find the interpreter.
# On first creation, postCreateCommand also runs uv sync, but on restarts
# only postStartCommand runs (which calls this script), so we need it here.
echo "Ensuring Python virtual environment..."
cd /workspace
if [ -f "pyproject.toml" ]; then
    uv sync 2>&1 | tail -1 || echo "WARNING: uv sync failed"
else
    echo "  No pyproject.toml found, skipping"
fi
echo ""

# Step 2: Load .env file and export to current environment
load_env_file || echo "WARNING: Failed to load .env file"
echo ""

# Step 3: Persist environment variables to /etc/environment for non-interactive processes (MCP)
persist_env_to_system
echo ""

# Step 4: Persist environment variables to bashrc for interactive shells
persist_env_to_bashrc
echo ""

# Step 5: Configure git
configure_git
echo ""

# Step 6: Configure GitHub CLI
configure_github_cli
echo ""

# Step 7: Add convenience aliases
add_convenience_aliases
echo ""

# Step 8: Fix Claude plugin path compatibility between host and container
fix_claude_plugin_paths
echo ""

# Step 9: Fix Docker socket permissions for Docker-from-Docker (MCP servers)
fix_docker_socket_permissions
echo ""

# Step 10: Initialize quber-workflow (Claude settings, hooks, skills)
initialize_quber_workflow
echo ""

echo "==============================================="
echo "  Startup Configuration Complete"
echo "==============================================="
