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
# 4. Install pre-commit git hooks for code quality checks

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
echo "Installing dependencies with UV..."
uv sync --dev
uv add --dev pre-commit

# Step 2: Configure shell to use project virtual environment
# Only add if not already present to avoid duplicates
if ! grep -q 'export PATH="/workspace/.venv/bin:$PATH"' /home/vscode/.bashrc; then
    echo "Adding virtual environment to PATH..."
    echo 'export PATH="/workspace/.venv/bin:$PATH"' >> /home/vscode/.bashrc
fi

# Step 3: Install pre-commit hooks for automated code quality checks
echo "Installing pre-commit hooks..."
/workspace/.venv/bin/pre-commit install

echo "Workspace setup completed. All dependencies installed and pre-commit hooks configured."

# Step 4: Run personal configuration setup if enabled
if [ -f "/workspace/.devcontainer/personal-setup.sh" ]; then
    echo "Checking for personal development environment setup..."
    /workspace/.devcontainer/personal-setup.sh
fi
