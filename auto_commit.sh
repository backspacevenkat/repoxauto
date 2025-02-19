#!/bin/bash
# Navigate to project root
cd "$(dirname "$0")"

# Check if there are any changes
if git status --porcelain | grep .; then
  # Stage all changes
  git add -A
  
  # Commit with timestamp and force push to 'main' with --no-verify to bypass checks
  git commit -m "Auto commit $(date '+%Y-%m-%d %H:%M:%S')"
  git push --force --no-verify origin main
fi
