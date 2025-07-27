#!/bin/bash
# Personal Development Tools Installation Script
# This script installs personal tools when ENABLE_PERSONAL_DOTFILES is set

# Ensure this script is executable
chmod +x "$0"

set -e

echo "🔍 Checking for personal configuration..."

# Check if personal configuration is enabled
if [[ "${ENABLE_PERSONAL_DOTFILES}" != "true" ]]; then
    echo "ℹ️  Personal dotfiles not enabled. Skipping personal tool installation."
    exit 0
fi

echo "✅ Personal configuration enabled. Installing personal tools..."

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to install tool if not present
install_if_missing() {
    local tool="$1"
    local install_cmd="$2"

    if command_exists "$tool"; then
        echo "✅ $tool already installed"
    else
        echo "🔧 Installing $tool..."
        eval "$install_cmd"
    fi
}

# Update package lists
echo "📦 Updating package lists..."
sudo apt-get update -qq

# Install essential tools for personal workflow
echo "🛠️  Installing personal development tools..."

# fzf - Fuzzy finder (essential for shell functions)
install_if_missing "fzf" "sudo apt-get install -y fzf"

# zoxide - Smart directory navigation
if ! command_exists "zoxide"; then
    echo "🔧 Installing zoxide..."
    curl -sS https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | bash
    # Add to PATH for current session
    export PATH="$HOME/.local/bin:$PATH"
fi

# starship - Shell prompt
if ! command_exists "starship"; then
    echo "🔧 Installing starship..."
    curl -sS https://starship.rs/install.sh | sh -s -- --yes
    # Add to PATH for current session
    export PATH="$HOME/.local/bin:$PATH"
fi

# keychain - SSH key management
install_if_missing "keychain" "sudo apt-get install -y keychain"

# tmux - Terminal multiplexer (essential for workflow)
install_if_missing "tmux" "sudo apt-get install -y tmux"

# stow - Dotfiles symlink management
install_if_missing "stow" "sudo apt-get install -y stow"

# Additional tools that might be useful
echo "🔧 Installing additional utilities..."
sudo apt-get install -y \
    tree \
    htop \
    ncdu \
    jq \
    curl \
    wget \
    2>/dev/null || echo "⚠️  Some optional tools may not be available"

# Install git-delta separately (newer tool, may not be in all repos)
if ! command_exists "delta"; then
    echo "🔧 Installing git-delta..."
    if curl -s https://api.github.com/repos/dandavison/delta/releases/latest | grep -q "browser_download_url.*x86_64.*linux.*musl"; then
        DELTA_URL=$(curl -s https://api.github.com/repos/dandavison/delta/releases/latest | grep "browser_download_url.*x86_64.*linux.*musl" | cut -d '"' -f 4)
        curl -L "$DELTA_URL" | tar -xz -C /tmp
        sudo mv /tmp/delta-*/delta /usr/local/bin/
        echo "✅ git-delta installed"
    else
        echo "⚠️  git-delta not available for this architecture"
    fi
fi

echo "🏠 Setting up dotfiles..."

# Clone and set up dotfiles if specified
if [[ -n "${DOTFILES_REPO}" ]]; then
    DOTFILES_DIR="$HOME/dotfiles"

    if [[ ! -d "$DOTFILES_DIR" ]]; then
        echo "📥 Cloning dotfiles from ${DOTFILES_REPO}..."
        git clone "$DOTFILES_REPO" "$DOTFILES_DIR"
    else
        echo "📁 Dotfiles directory already exists"
    fi

    # Navigate to linux subdirectory if it exists
    if [[ -d "$DOTFILES_DIR/linux" ]]; then
        cd "$DOTFILES_DIR/linux"
        echo "🔗 Setting up dotfiles with stow..."

        # Use stow to create symlinks for dotfiles
        # This assumes your dotfiles are organized for stow
        stow -v -t "$HOME" . 2>/dev/null || {
            echo "⚠️  Stow failed, attempting manual symlink setup..."
            # Fallback: create symlinks manually for common files
            for file in .bashrc .bash_aliases .tmux.conf; do
                if [[ -f "$file" ]]; then
                    ln -sf "$PWD/$file" "$HOME/$file"
                    echo "🔗 Linked $file"
                fi
            done
        }
    fi
fi

# Initialize keychain if SSH keys exist
if [[ -f "$HOME/.ssh/id_rsa" ]] || [[ -f "$HOME/.ssh/id_ed25519" ]]; then
    echo "🔑 Initializing keychain for SSH keys..."
    keychain --eval --agents ssh id_rsa id_ed25519 2>/dev/null || true
fi

# Source the new configuration if bashrc was updated
if [[ -f "$HOME/.bashrc" ]]; then
    echo "🔄 Sourcing updated .bashrc..."
    source "$HOME/.bashrc" || true
fi

echo "🎉 Personal development environment setup complete!"
echo "💡 Restart your terminal or run 'source ~/.bashrc' to activate all changes."
