#!/bin/bash
# DevContainer Post-Create Setup Script
# Runs ONCE after the devcontainer is created.
# For environment setup that runs on every restart, see startup.sh.

set -e

echo "Starting workspace setup..."

# Ensure UV is available in PATH
export PATH="$HOME/.local/bin:$PATH"

# Step 1: Install all project dependencies
echo "Installing dependencies with UV..."
uv sync
# Step 2: Install pre-commit hooks
if [ -d "/workspace/.git" ] && command -v pre-commit > /dev/null 2>&1; then
    echo "Installing pre-commit hooks..."
    cd /workspace
    pre-commit install 2>/dev/null || echo "  pre-commit install failed (non-critical)"
fi

# Step 3: Run startup.sh (env persistence, git, gh CLI)
echo "Running startup configuration..."
/usr/local/bin/devcontainer-startup

echo "Workspace setup completed."

# Step 4: Run personal configuration if present
if [ -f "/workspace/.devcontainer/personal-setup.sh" ]; then
    echo "Running personal development environment setup..."
    /workspace/.devcontainer/personal-setup.sh
fi
