FROM maximhq/bifrost:latest

USER root

# Install Node.js runtime for STDIO MCP servers
RUN apk add --no-cache nodejs npm

# Pre-cache the GitHub MCP server package to avoid runtime downloads
RUN npx -y @modelcontextprotocol/server-github --help 2>/dev/null || true

# Copy Bifrost config
COPY bifrost-config.json /app/data/config.json
RUN chown appuser:appuser /app/data/config.json

USER appuser
