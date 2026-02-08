# Use the official Python devcontainer base image
FROM mcr.microsoft.com/vscode/devcontainers/python:3.11

# Update package lists and install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    vim \
    redis-tools \
    uuid-runtime \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Switch to vscode user for user-specific installations
USER vscode

# Install UV package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# Install Starship prompt
RUN curl -sS https://starship.rs/install.sh | sh -s -- --yes \
    && echo 'eval "$(starship init bash)"' >> ~/.bashrc

# Install just command runner
RUN curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/.local/bin

# Install Claude Code (native installer - no Node.js dependency)
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && echo "alias claudeyolo='claude --dangerously-skip-permissions'" >> ~/.bashrc

# Verify installations
RUN uv --version || echo "UV installed, will be available after sourcing bashrc"
RUN ~/.local/bin/claude --version || echo "Claude Code installed, will be available after authentication"

# Switch back to root for any additional setup
USER root

# Create workspace directory
WORKDIR /workspace

# Set the default user back to vscode
USER vscode
