# Use the official Python devcontainer base image
FROM mcr.microsoft.com/vscode/devcontainers/python:3.11

# Update package lists
RUN apt-get update

# Install Node.js 18.x
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs

# Verify Node.js installation
RUN node --version && npm --version

# Install additional system dependencies if needed
RUN apt-get install -y \
    git \
    curl \
    wget \
    vim \
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

# Set up npm global directory and install Claude Code
RUN mkdir -p ~/.npm-global ~/.local/bin \
    && npm config set prefix '~/.npm-global' \
    && echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc \
    && npm install -g @anthropic-ai/claude-code \
    && ln -sfn ~/.npm-global/bin/claude ~/.local/bin/claude \
    && echo "alias claudeyolo='claude --dangerously-skip-permissions'" >> ~/.bashrc

# Verify installations
RUN source ~/.bashrc && uv --version || echo "UV installed, will be available after sourcing bashrc"
RUN claude --version || echo "Claude Code installed, will be available after authentication"

# Switch back to root for any additional setup
USER root

# Create workspace directory
WORKDIR /workspace

# Set the default user back to vscode
USER vscode
