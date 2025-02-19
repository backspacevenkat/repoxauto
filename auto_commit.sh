#!/bin/bash
# Navigate to project root
cd "$(dirname "$0")"

# Check if there are any changes
if git status --porcelain | grep .; then
  # Add all changes, commit with the current date/time, and push to 'main'
  git add -A
  git commit -m "Auto commit $(date '+%Y-%m-%d %H:%M:%S')"
  git push origin main
fi
