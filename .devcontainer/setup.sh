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
# Step 2: Activate checked-in pre-commit hooks
if [ -d "/workspace/.git" ]; then
    echo "Activating pre-commit hooks via core.hooksPath..."
    cd /workspace
    git config core.hooksPath .githooks
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
