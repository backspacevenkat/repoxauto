#!/bin/bash
# Navigate to project root
cd "$(dirname "$0")"

# Check if there are any changes
if git status --porcelain | grep .; then
  # Stage all changes
  git add -A
  
  # Check for secrets in staged changes (excluding auto_commit.sh) using keywords
  if git diff --cached -- ':!auto_commit.sh' | grep -Ei "openai api key|github personal access token"; then
    echo "Secrets detected in committed changes. Skipping commit."
    exit 1
  fi
  
  # Commit with timestamp and push to 'main'
  git commit -m "Auto commit $(date '+%Y-%m-%d %H:%M:%S')"
  git push origin main
fi
