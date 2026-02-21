---
name: devserver
description: Start a local HTTP dev server for browsing HTML files in `docs/architecture-map/`. Supports saving layouts to JSON files. Serves files on a port that VS Code can auto-forward to your local browser via the Remote SSH extension. Usage - /devserver [port] [directory]
user-invocable: true
allowed-tools: Bash
---

# Dev Server Skill

Starts a lightweight Python HTTP server for previewing HTML playgrounds and devtools in a VS Code Remote SSH environment. Supports PUT for persisting layout JSON files.

## How It Works

1. Starts `docs/architecture-map/_devserver.py` in the background on the specified port
2. VS Code detects the port and offers to forward it
3. You open `http://localhost:<port>/<filename>` in your local browser
4. Layout saves (PUT requests to .json files) write directly to the filesystem so they can be committed to the repo

## Usage

```
/devserver              # Serves docs/architecture-map/ on port 8765
/devserver 9000         # Serves docs/architecture-map/ on port 9000
/devserver 9000 docs    # Serves docs/ on port 9000
```

## Instructions

When this skill is invoked:

1. Parse optional arguments: first arg is port (default 8765), second arg is directory relative to repo root (default `docs/architecture-map`)
2. Resolve the directory to an absolute path from the repository root
3. Check if a server is already running on that port using `lsof -i :<port>`. If so, inform the user it's already running and give the URL
4. Start the server in the background using `python3 docs/architecture-map/_devserver.py <port>` from within the target directory
5. List the available HTML files in the directory
6. Tell the user:
   - The server is running on port `<port>`
   - VS Code should offer to forward the port in the Ports tab
   - The URL pattern: `http://localhost:<port>/<filename>.html`
   - List the available HTML files as clickable suggestions
   - Layout saves will persist to `architecture_layouts.json` (committable to repo)
7. To stop the server later, the user can run: `kill $(lsof -t -i :<port>)`
