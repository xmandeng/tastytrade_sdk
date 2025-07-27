# Personal Devcontainer Customization

This directory includes infrastructure for personal devcontainer customization that doesn't affect other team members.

## Quick Setup

1. Copy the example configuration:
   ```bash
   cp .devcontainer/devcontainer.local.json.example .devcontainer/devcontainer.local.json
   ```

2. Edit `devcontainer.local.json` with your personal settings:
   - Set your dotfiles repository URL
   - Add personal VS Code extensions
   - Configure personal environment variables

3. Rebuild the devcontainer to apply changes

## How It Works

### Personal Configuration Override
- `devcontainer.local.json` (gitignored) extends the base `devcontainer.json`
- Only exists for users who want personal customization
- VS Code automatically merges configurations when both files exist

### Conditional Tool Installation
- Personal tools are only installed when `ENABLE_PERSONAL_DOTFILES=true`
- The `personal-setup.sh` script handles tool installation automatically
- Gracefully skips installation if personal config is not enabled

### Dotfiles Integration
- Automatically clones your dotfiles repository during container creation
- Uses GNU Stow for proper symlink management
- Supports subdirectory structure (e.g., `/linux` subdirectory)

## Supported Tools

The personal setup installs these tools when enabled:

### Essential CLI Tools
- **fzf** - Fuzzy finder for command history and file selection
- **zoxide** - Smart directory navigation with frequency-based jumping
- **starship** - Cross-shell prompt with Git integration
- **keychain** - SSH key management for persistent authentication
- **tmux** - Terminal multiplexer for session management
- **stow** - Symlink manager for dotfiles

### Additional Utilities
- **tree** - Directory structure visualization
- **htop** - Interactive process viewer
- **ncdu** - Disk usage analyzer
- **jq** - JSON processor
- **git-delta** - Enhanced git diff viewer

## Configuration Example

```json
{
  "name": "TastyTrade SDK with Personal Dotfiles",

  "customizations": {
    "vscode": {
      "extensions": [
        "PKief.material-icon-theme",
        "ms-vscode.vscode-json"
      ],
      "settings": {
        "workbench.colorTheme": "Material Theme",
        "editor.fontSize": 14
      }
    }
  },

  "remoteEnv": {
    "ENABLE_PERSONAL_DOTFILES": "true",
    "DOTFILES_REPO": "https://github.com/yourusername/dotfiles.git"
  }
}
```

## Dotfiles Repository Structure

Your dotfiles repository should be organized for GNU Stow:

```
dotfiles/
├── linux/              # Platform-specific configs
│   ├── .bashrc         # Shell configuration
│   ├── .bash_aliases   # Shell aliases
│   ├── .tmux.conf      # Tmux configuration
│   └── .config/        # Application configs
└── install.sh          # Optional installation script
```

## Team Member Setup

Other team members can create their own personal setup:

1. Copy the example file to create their own `devcontainer.local.json`
2. Set their own dotfiles repository URL
3. Add their preferred extensions and settings
4. The setup is completely independent and doesn't affect others

## Troubleshooting

### Tools Not Installing
- Check that `ENABLE_PERSONAL_DOTFILES=true` in your local config
- Verify the personal-setup.sh script has execute permissions
- Check container logs for specific error messages

### Dotfiles Not Applied
- Ensure your dotfiles repository is publicly accessible
- Check that the repository structure works with GNU Stow
- Verify the `/linux` subdirectory exists if using platform-specific configs

### VS Code Extensions Not Loading
- Confirm extensions are listed in your `devcontainer.local.json`
- Rebuild the container after adding new extensions
- Check VS Code extension marketplace for availability

## Security Notes

- Personal configuration files are gitignored for security
- SSH keys and credentials are never committed to the repository
- Dotfiles repositories should not contain sensitive information
- Use environment variables for secrets and API keys

## Advanced Customization

### Custom Installation Scripts
Create additional setup scripts in `.devcontainer/personal/` for complex configurations.

### Platform Detection
The setup script can detect platform-specific requirements and adjust accordingly.

### Tool Version Pinning
Modify `personal-setup.sh` to install specific versions of tools for consistency.
