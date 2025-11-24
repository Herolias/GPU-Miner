# Git Workflow Guide

## Branch Structure

- **`main`** - Stable, production-ready code. Protected branch.
- **`dev`** - Active development branch. All new features go here first.

## Development Workflow

### For New Features

1. **Start from dev branch:**
   ```bash
   git checkout dev
   git pull origin dev
   ```

2. **Create a feature branch (optional):**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes and commit:**
   ```bash
   git add .
   git commit -m "feat: description of your changes"
   ```

4. **Push to dev:**
   ```bash
   git checkout dev
   git merge feature/your-feature-name  # if using feature branch
   git push origin dev
   ```

### Releasing to Main

When dev is stable and ready for release:

```bash
# Switch to main
git checkout main
git pull origin main

# Merge dev into main
git merge dev

# Tag the release
git tag -a v1.1.0 -m "Release v1.1.0"

# Push everything
git push origin main --tags
```

## Quick Reference

```bash
# Switch to dev branch
git checkout dev

# Switch to main branch  
git checkout main

# See all branches
git branch -a

# Pull latest changes
git pull

# Push your commits
git push
```

## Commit Message Convention

Use conventional commits for better changelog generation:

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `perf:` - Performance improvements
- `test:` - Adding tests
- `chore:` - Maintenance tasks

Examples:
```
feat: Add support for multiple GPUs
fix: Resolve database deadlock issue
docs: Update installation instructions
refactor: Simplify wallet management logic
```
