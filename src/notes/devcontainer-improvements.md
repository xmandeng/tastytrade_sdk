# Devcontainer & Dockerfile Improvement Plan

*Created: 2025-07-27*
*Status: In Progress*

## Overview
This document tracks incremental improvements to the devcontainer setup for better performance, security, and maintainability. Items are organized by priority and can be tackled across multiple development sessions.

## Session Log
| Date | Phase | Items Completed | Notes |
|------|-------|----------------|-------|
| 2025-07-27 | Planning | Initial assessment | Created improvement plan |

---

## Phase 1: Critical Issues (P0) 🔴
*Target: Complete within 1-2 sessions*

### Security & Reliability
- [ ] **Pin UV installation version** *(15 min)*
  - Current: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Target: Use specific version with checksum verification
  - Risk: Supply chain attacks, version drift

- [ ] **Fix Cargo environment issue** *(5 min)*
  - Current: `source $HOME/.cargo/env` (file doesn't exist)
  - Status: ✅ **COMPLETED** - Fixed in postCreateCommand

- [ ] **Add error handling to postCreateCommand** *(10 min)*
  - Current: Single long command that can fail silently
  - Target: Break into steps with proper error handling

- [ ] **Remove redundant git installation** *(2 min)*
  - Current: Installing git twice (base image + Dockerfile)
  - Target: Remove from Dockerfile line 16

### Performance Issues
- [ ] **Consolidate package installations** *(10 min)*
  - Current: Multiple RUN commands with cleanup scattered
  - Target: Single RUN layer with proper cleanup
  - Impact: Smaller image, faster builds

- [ ] **Optimize USER switches** *(5 min)*
  - Current: Multiple USER switches create unnecessary layers
  - Target: Minimize USER switches, group operations

---

## Phase 2: High Impact Improvements (P1) 🟡
*Target: Complete within 3-4 sessions*

### Extension Optimization
- [ ] **Audit and reduce extensions** *(30 min)*
  - Current: 89 extensions (excessive)
  - Target: ~40 essential extensions
  - Categories to review:
    - [ ] Remove: `ms-vscode.live-server`, `ms-edgedevtools.vscode-edge-devtools` (not relevant)
    - [ ] Remove: Duplicate Git extensions (keep GitLens + 1-2 others)
    - [ ] Remove: `csstools.postcss`, `ecmel.vscode-html-css` (not CSS project)
    - [ ] Keep: All Python, Jupyter, Docker, Claude Code essentials

- [ ] **Group extensions logically** *(15 min)*
  - Current: Mixed ordering
  - Target: Logical grouping with comments

### Configuration Improvements
- [ ] **Make Python version configurable** *(20 min)*
  - Current: Hardcoded 3.11 paths
  - Target: Use build args and variables
  - Files: Dockerfile, devcontainer.json

- [ ] **Simplify postCreateCommand** *(25 min)*
  - Current: Complex single-line command
  - Target: Break into logical steps with error handling
  - Consider: Move to separate script file

- [ ] **Add onCreateCommand** *(15 min)*
  - Current: Only postCreateCommand
  - Target: Separate one-time setup vs. every-restart setup

### Docker Optimization
- [ ] **Pin Node.js version** *(5 min)*
  - Current: `setup_18.x` (latest 18.x)
  - Target: Specific version like `18.19.0`

- [ ] **Add package cleanup after Node.js** *(5 min)*
  - Current: Missing cleanup after Node.js installation
  - Target: Add `&& apt-get clean && rm -rf /var/lib/apt/lists/*`

---

## Phase 3: Advanced Optimizations (P2) 🟢
*Target: Complete when time allows*

### Build Optimization
- [ ] **Implement multi-stage build** *(45 min)*
  - Current: Single stage with all tools
  - Target: Build stage + runtime stage
  - Benefit: Smaller final image

- [ ] **Add .dockerignore** *(10 min)*
  - Current: None
  - Target: Exclude unnecessary files from build context

- [ ] **Use specific base image tag** *(5 min)*
  - Current: `mcr.microsoft.com/vscode/devcontainers/python:3.11`
  - Target: Pin to specific digest or detailed version

### Advanced Configuration
- [ ] **Add development vs production modes** *(30 min)*
  - Current: Single configuration
  - Target: Environment-specific configs

- [ ] **Optimize port forwarding** *(10 min)*
  - Current: Forward all ports always
  - Target: Conditional forwarding based on services

- [ ] **Add container health checks** *(20 min)*
  - Current: No health monitoring
  - Target: Health checks for key services

### Developer Experience
- [ ] **Add pre-commit setup automation** *(15 min)*
  - Current: Manual pre-commit install in postCreateCommand
  - Target: Automatic detection and setup

- [ ] **Create development scripts** *(25 min)*
  - Target: Common development tasks in `scripts/` directory
  - Examples: `setup-dev.sh`, `run-tests.sh`, `reset-env.sh`

---

## Testing Checklist
After each phase, verify:

- [ ] Container builds successfully
- [ ] All extensions load without errors
- [ ] Python environment activates correctly
- [ ] UV commands work properly
- [ ] Pre-commit hooks function
- [ ] Port forwarding works for all services
- [ ] No regression in development workflow

## Rollback Procedures

### Quick Rollback
1. Keep backup of original files: `.devcontainer/Dockerfile.bak`, `.devcontainer/devcontainer.json.bak`
2. Use git to revert specific commits
3. Test with `devcontainer rebuild`

### Individual Component Rollback
- **Extensions**: Comment out problematic extensions, rebuild
- **Dockerfile**: Revert specific RUN commands
- **PostCreateCommand**: Break into smaller parts to isolate issues

## Implementation Notes

### Best Practices
- Test each change incrementally
- Keep backup copies of working configurations
- Document any custom modifications
- Consider team member preferences for extensions

### Common Pitfalls
- Don't remove extensions others on the team depend on
- Test UV installation thoroughly after pinning version
- Verify all Python paths after making version configurable
- Ensure port forwarding still works after optimization

### Performance Metrics to Track
- Container build time (target: < 3 minutes)
- Container startup time (target: < 30 seconds)
- VS Code ready time (target: < 1 minute)
- Image size (target: < 2GB)

---

## Future Considerations

### Potential Additions
- [ ] **Dev container features**: Consider using more devcontainer features instead of manual installation
- [ ] **Cache optimization**: Add BuildKit cache mounts for package managers
- [ ] **Security scanning**: Add container vulnerability scanning
- [ ] **Documentation**: Auto-generate devcontainer documentation

### Monitoring
- [ ] Set up container performance monitoring
- [ ] Track build times over time
- [ ] Monitor extension load times
- [ ] Survey team satisfaction with development environment

---

*💡 Tip: Tackle one phase at a time, test thoroughly, and update this document with your progress and any lessons learned.*
