FROM maximhq/bifrost:latest

USER root

# Install Node.js and Chromium dependencies for Playwright
RUN apk add --no-cache \
    nodejs npm \
    chromium \
    nss \
    freetype \
    harfbuzz \
    ca-certificates \
    ttf-freefont

# Tell Playwright to use system Chromium
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Symlink system Chromium to where Playwright expects Chrome
RUN mkdir -p /opt/google/chrome && \
    ln -sf /usr/bin/chromium-browser /opt/google/chrome/chrome

# Pre-cache the Playwright MCP server package
RUN npx -y @playwright/mcp@latest --help 2>/dev/null || true

# Copy Bifrost config
COPY bifrost-config.json /app/data/config.json
RUN chown appuser:appuser /app/data/config.json

USER appuser
