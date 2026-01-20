#!/bin/bash
# Development Container Post-Create Setup Script
#
# This script runs after the devcontainer is created to configure the workspace.
# It replaces the inline postCreateCommand in devcontainer.json for better maintainability.
#
# Steps performed:
# 1. Install Python dependencies using UV package manager
# 2. Add pre-commit development dependency
# 3. Configure shell environment to use project virtual environment
# 4. Configure shell aliases for development workflow
# 5. Install pre-commit git hooks for code quality checks
# 6. Install Pyright language server via UV
# 7. Configure Claude Code plugin marketplaces
# 8. Install Python LSP plugin for Claude Code

set -e

echo "Starting workspace setup..."

# Ensure UV is available in PATH
export PATH="$HOME/.local/bin:$PATH"

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
    echo 'export PATH="/workspace/.venv/bin:$PATH"' >> /home/vscode/.bashrc
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

# Step 3: Install pre-commit hooks for automated code quality checks
echo "Installing pre-commit hooks..."
/workspace/.venv/bin/pre-commit install

# Step 4: Install Pyright language server via UV
echo "Installing Pyright language server..."
uv tool install pyright || echo "Pyright already installed"

# Step 5: Configure Claude Code plugin marketplaces
echo "Configuring Claude Code plugin marketplaces..."
# Add official Anthropic plugin marketplace
claude plugin marketplace add anthropics/claude-plugins-official 2>/dev/null || echo "Official marketplace already added or Claude not authenticated"
# Add demo marketplace with examples
claude plugin marketplace add anthropics/claude-code 2>/dev/null || echo "Demo marketplace already added or Claude not authenticated"

# Step 6: Install Python LSP plugin (requires authentication)
echo "Installing Python LSP plugin (pyright-lsp)..."
claude plugin install pyright-lsp 2>/dev/null || echo "Python LSP plugin install skipped (requires Claude authentication)"

echo "Workspace setup completed. All dependencies installed and pre-commit hooks configured."

# Step 4: Run personal configuration setup if enabled
if [ -f "/workspace/.devcontainer/personal-setup.sh" ]; then
    echo "Checking for personal development environment setup..."
    /workspace/.devcontainer/personal-setup.sh
fi
