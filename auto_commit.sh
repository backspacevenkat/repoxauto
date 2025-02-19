#!/bin/bash
# Navigate to project root
cd "$(dirname "$0")"

# Check if there are any changes
if git status --porcelain | grep .; then
  # Stage all changes
  git add -A
  
  # Check for secrets in staged changes using keywords, excluding lines from auto_commit.sh
  if git diff --cached | grep -Ei "openai api key|github personal access token" | grep -Ev "auto_commit.sh"; then
    echo "Secrets detected in committed changes. Skipping commit and unstaging changes."
    git reset
    exit 1
  fi
  
  # Commit with timestamp and push to 'main'
  git commit -m "Auto commit $(date '+%Y-%m-%d %H:%M:%S')"
  git push origin main
fi
