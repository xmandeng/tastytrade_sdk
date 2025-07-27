# Use the official Python devcontainer base image
FROM mcr.microsoft.com/vscode/devcontainers/python:3.11

# Update package lists
RUN apt-get update

# Install Node.js 18.x
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs

# Verify Node.js installation
RUN node --version && npm --version

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Verify Claude Code installation
RUN claude --version || echo "Claude Code installed, will be available after authentication"

# Install additional system dependencies if needed
RUN apt-get install -y \
    git \
    curl \
    wget \
    vim \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set up vscode user's npm global directory
USER vscode
RUN mkdir -p ~/.npm-global \
    && npm config set prefix '~/.npm-global' \
    && echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc

# Switch back to root for any additional setup
USER root

# Create workspace directory
WORKDIR /workspace

# Set the default user back to vscode
USER vscode
