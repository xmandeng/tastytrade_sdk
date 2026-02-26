FROM ubuntu:24.04 AS base

# Install Python 3.13 via deadsnakes PPA
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.13 \
    python3.13-venv \
    python3.13-dev \
    && rm -rf /var/lib/apt/lists/*

# Create symlinks for python commands
RUN ln -sf /usr/bin/python3.13 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.13 /usr/bin/python

# Install pip for Python 3.13
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.13

# Install system dependencies and locale support
RUN apt-get update && apt-get install -y \
    git \
    curl \
    sudo \
    locales \
    jq \
    uuid-runtime \
    vim \
    # Node.js for development tools (pre-commit hooks, etc.)
    nodejs \
    npm \
    # Docker CLI for Docker-from-Docker (MCP servers)
    ca-certificates \
    gnupg \
    lsb-release \
    && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen \
    && dpkg-reconfigure --frontend=noninteractive locales \
    && update-locale LANG=en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI from official repository
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y docker-ce-cli docker-buildx-plugin docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Set locale environment variables
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Verify locale settings
RUN locale -a | grep -q en_US.utf8 && echo "Locale en_US.UTF-8 installed successfully" || exit 1

# Install uv for fast Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
# Use copy mode for UV installations (hardlinks don't work across Docker layers)
ENV UV_LINK_MODE=copy

# Create non-root user with sudo access
ARG USERNAME=developer
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN (groupadd --gid $USER_GID $USERNAME 2>/dev/null || groupmod -n $USERNAME $(getent group $USER_GID | cut -d: -f1)) \
    && (useradd --uid $USER_UID --gid $USER_GID -m $USERNAME 2>/dev/null || usermod -l $USERNAME -d /home/$USERNAME -m $(getent passwd $USER_UID | cut -d: -f1)) \
    && echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Add developer user to docker group for Docker-from-Docker
# Note: The actual docker group GID will come from the host via the mounted socket
RUN groupadd -f docker \
    && usermod -aG docker $USERNAME

# Copy uv to user's local bin
RUN mkdir -p /home/$USERNAME/.local/bin \
    && cp /root/.local/bin/uv /home/$USERNAME/.local/bin/ \
    && chown -R $USERNAME:$USERNAME /home/$USERNAME/.local

#############################################
# DEVELOPMENT STAGE
# Comment out this entire section for production builds
#############################################
FROM base AS development

# Install Claude CLI for AI-assisted development
# Installation: https://docs.claude.com/claude-code/install
# Note: Install script requires bash, not sh
# Install directly as developer user to avoid conflicts from multiple installation locations
USER $USERNAME
RUN curl -fsSL https://claude.ai/install.sh | bash
# PATH already includes /home/$USERNAME/.local/bin from final stage

# Install GitHub CLI for git automation (requires root)
USER root
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
    dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
    tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && \
    apt-get install gh -y && \
    rm -rf /var/lib/apt/lists/*

# Install just task runner for development commands (requires root)
RUN curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin

USER $USERNAME

# Additional dev tools can be added here
# Examples: starship, fzf, zoxide, etc.

#############################################
# PRODUCTION STAGE
# Minimal runtime without dev dependencies
#############################################
FROM base AS production

# No dev tools installed
# Only runtime dependencies from base stage

#############################################
# FINAL STAGE SELECTION
# Defaults to development for local work
# Change to 'FROM production AS final' or use --target flag for production builds
#############################################
FROM development AS final

# Set up workspace directory
WORKDIR /workspace

# Copy startup script
COPY .devcontainer/startup.sh /usr/local/bin/devcontainer-startup
USER root
RUN chmod +x /usr/local/bin/devcontainer-startup
USER $USERNAME

# Update PATH for the user
ENV PATH="/home/$USERNAME/.local/bin:$PATH"

# Set Python to run in unbuffered mode
ENV PYTHONUNBUFFERED=1

# Pre-create directories for better caching
RUN mkdir -p /home/$USERNAME/.cache/uv

# Install ruff as a standalone tool so it's available at container start.
# Lives at ~/.local/bin/ruff — outside /workspace, so the bind mount can't hide it.
# Pin to match pyproject.toml: ruff>=0.12.5
RUN uv tool install "ruff>=0.12.5"

# OPTIMIZATION: Pre-install heavy dependencies in Docker layer
# This significantly speeds up devcontainer rebuilds and worktree setup
# Cache stays valid unless pyproject.toml changes
COPY --chown=$USERNAME:$USERNAME pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project || uv sync --no-install-project
# Clean up project files (we'll mount the real ones)
RUN rm -f pyproject.toml uv.lock
