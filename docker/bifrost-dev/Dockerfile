FROM maximhq/bifrost:latest

USER root

# Install Node.js for GitHub MCP and Python/pip for Atlassian MCP
RUN apk add --no-cache nodejs npm python3 py3-pip

# Pre-cache the GitHub MCP server package
RUN npx -y @modelcontextprotocol/server-github --help 2>/dev/null || true

# Install the Atlassian MCP server (sooperset/mcp-atlassian)
RUN pip3 install --break-system-packages mcp-atlassian

# Copy Bifrost config
COPY bifrost-config.json /app/data/config.json
RUN chown appuser:appuser /app/data/config.json

USER appuser
