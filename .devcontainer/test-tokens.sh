#!/bin/bash
# Diagnostic script to verify environment variables and authentication
# Usage: bash .devcontainer/test-tokens.sh

echo "=== Testing Environment Variables in DevContainer ==="
echo

# Test GitHub Token
echo "GitHub Token:"
if [ -n "$GH_TOKEN" ]; then
    echo "  GH_TOKEN is set (length: ${#GH_TOKEN})"
else
    echo "  GH_TOKEN is not set"
fi

echo

# Test API Keys
echo "API Keys:"
if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "  ANTHROPIC_API_KEY is set (length: ${#ANTHROPIC_API_KEY})"
else
    echo "  ANTHROPIC_API_KEY is not set"
fi

if [ -n "$OPENAI_API_KEY" ]; then
    echo "  OPENAI_API_KEY is set (length: ${#OPENAI_API_KEY})"
else
    echo "  OPENAI_API_KEY is not set"
fi

if [ -n "$PYDANTIC_LOGFIRE_TOKEN" ]; then
    echo "  PYDANTIC_LOGFIRE_TOKEN is set (length: ${#PYDANTIC_LOGFIRE_TOKEN})"
else
    echo "  PYDANTIC_LOGFIRE_TOKEN is not set"
fi

echo

# Test Atlassian/Jira
echo "Atlassian/Jira:"
if [ -n "$ATLASSIAN_SITE_NAME" ]; then
    echo "  ATLASSIAN_SITE_NAME is set: $ATLASSIAN_SITE_NAME"
else
    echo "  ATLASSIAN_SITE_NAME is not set"
fi

if [ -n "$ATLASSIAN_USER_EMAIL" ]; then
    echo "  ATLASSIAN_USER_EMAIL is set: $ATLASSIAN_USER_EMAIL"
else
    echo "  ATLASSIAN_USER_EMAIL is not set"
fi

if [ -n "$ATLASSIAN_API_TOKEN" ]; then
    echo "  ATLASSIAN_API_TOKEN is set (length: ${#ATLASSIAN_API_TOKEN})"
else
    echo "  ATLASSIAN_API_TOKEN is not set"
fi

echo

# Test LangSmith
echo "LangSmith:"
if [ -n "$CC_LANGSMITH_API_KEY" ]; then
    echo "  CC_LANGSMITH_API_KEY is set (length: ${#CC_LANGSMITH_API_KEY})"
else
    echo "  CC_LANGSMITH_API_KEY is not set"
fi

if [ -n "$CC_LANGSMITH_PROJECT" ]; then
    echo "  CC_LANGSMITH_PROJECT is set: $CC_LANGSMITH_PROJECT"
else
    echo "  CC_LANGSMITH_PROJECT is not set"
fi

if [ -n "$TRACE_TO_LANGSMITH" ]; then
    echo "  TRACE_TO_LANGSMITH is set: $TRACE_TO_LANGSMITH"
else
    echo "  TRACE_TO_LANGSMITH is not set"
fi

echo

# Test gh CLI authentication
echo "GitHub CLI Authentication:"
if command -v gh &> /dev/null; then
    if [ -n "$GH_TOKEN" ]; then
        if gh auth status &> /dev/null; then
            echo "  gh CLI is authenticated"
            gh auth status 2>&1 | grep "Logged in" | sed 's/^/  /'
        else
            echo "  gh CLI authentication failed"
        fi
    else
        echo "  No GitHub token available for gh CLI"
    fi
else
    echo "  gh CLI is not installed"
fi

echo

# Test .env file
echo "Environment File:"
if [ -f "/workspace/.env" ]; then
    echo "  .env file is mounted"
    echo "  File contains $(grep -c '=' /workspace/.env 2>/dev/null || echo 0) variable(s)"
else
    echo "  .env file is not mounted (optional)"
fi

echo

# Test /etc/environment persistence
echo "System Environment (/etc/environment):"
if grep -q "^GH_TOKEN=" /etc/environment 2>/dev/null; then
    echo "  Variables are persisted to /etc/environment"
else
    echo "  Variables are NOT persisted to /etc/environment (run startup.sh first)"
fi

echo
echo "=== Test Complete ==="
