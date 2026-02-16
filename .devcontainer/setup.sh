#!/bin/bash
# Development Container Post-Create Setup Script
#
# This script runs after the devcontainer is created to configure the workspace.
# It replaces the inline postCreateCommand in devcontainer.json for better maintainability.
#
# Steps performed:
# 1. Install Python dependencies using UV package manager
# 2. Configure shell environment and aliases
# 3. Initialize quber-workflow (generates .claude/ and CLAUDE.md)
# 4. Install pre-commit git hooks
# 5. Install Pyright language server via UV
# 6. Run personal configuration setup (if present)

set -e

echo "Starting workspace setup..."

# Ensure UV is available in PATH
export PATH="$HOME/.local/bin:$PATH"

# Step 1: Install all project dependencies including development tools
echo "Installing dependencies with UV (including dev extras)..."
# Install base + optional 'dev' extras defined under [project.optional-dependencies]
uv sync --all-extras || uv sync

# Ensure dev tooling explicitly (fallback if extras not applied)
uv add --dev pytest pytest-cov pytest-asyncio pytest-mock ruff mypy pre-commit || true

# Step 2: Configure shell to use project virtual environment
# Only add if not already present to avoid duplicates
if ! grep -q 'export PATH="/workspace/.venv/bin:$PATH"' /home/vscode/.bashrc; then
    echo "Adding virtual environment to PATH..."
    cat >> /home/vscode/.bashrc << 'EOF'

# Activate virtual environment
export VIRTUAL_ENV="/workspace/.venv"
export PATH="/workspace/.venv/bin:$PATH"
EOF
fi

# Step 2a: Source .env file for environment variables (LangSmith, API keys, etc.)
if ! grep -q 'source /workspace/.env' /home/vscode/.bashrc; then
    echo "Adding .env sourcing to bashrc..."
    cat >> /home/vscode/.bashrc << 'EOF'

# Load environment variables from .env file
if [ -f /workspace/.env ]; then
    set -a
    source /workspace/.env
    set +a
fi
EOF
fi

# Step 2b: Configure shell aliases
# Only add if not already present to avoid duplicates
if ! grep -q '# Project Shell Aliases' /home/vscode/.bashrc; then
    echo "Adding shell aliases..."
    cat >> /home/vscode/.bashrc << 'EOF'

# Project Shell Aliases
# Shell
alias ls='ls --color=auto'
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias c="clear"
alias s="source ~/.bashrc"

# grep w/ PCRE search ("-P")
alias grep="/bin/grep --color=auto"
alias fgrep='/bin/fgrep --color=auto'
alias egrep='/bin/egrep --color=auto'

# DEV
alias python=python3
alias awslogin='aws sso login --profile ${AWS_PROFILE}'

# Git add incl dotfiles
alias ga="git add . -A"
alias gs="git status"
alias gc="git commit -m"
alias gpush="git push"
alias gpull="git pull"
alias gco="git branch -r | sed 's/^ *origin\///' | fzf --cycle --no-info --border=rounded --reverse | xargs git checkout"
alias gcd="git checkout develop"
alias gl="git log --oneline --graph --all --decorate --parents"
alias gstat="git diff --stat"
alias uncommit="git reset --soft HEAD~1"
alias forget="git reset --hard HEAD~1"
alias cleanup="git branch -vv | grep 'origin/.*: gone]' | awk '{print \$1}' | xargs git branch -D"

# TMUX
alias t="tmux"
alias ta="tmux a -t"
alias tls="tmux ls"
alias tn="tmux new -t"
alias tkill="tmux kill-server"
EOF
fi

# Step 3: Initialize Claude Code workflow configuration (quber-workflow)
# The .claude/ volume mount is created as root — fix ownership for vscode user
sudo chown -R vscode:vscode /workspace/.claude

echo "Initializing quber-workflow configuration..."
/workspace/.venv/bin/quber-workflow init --config /workspace/.claude/.quber-workflow.yaml

# Step 4: Install pre-commit hooks for automated code quality checks
echo "Installing pre-commit hooks..."
/workspace/.venv/bin/pre-commit install

# Step 5: Install Pyright language server via UV
echo "Installing Pyright language server..."
uv tool install pyright || echo "Pyright already installed"

echo "Workspace setup completed. All dependencies installed and pre-commit hooks configured."

# Step 6: Run personal configuration setup if enabled
if [ -f "/workspace/.devcontainer/personal-setup.sh" ]; then
    echo "Checking for personal development environment setup..."
    /workspace/.devcontainer/personal-setup.sh
fi
