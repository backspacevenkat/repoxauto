#!/bin/bash
# Navigate to project root
cd "$(dirname "$0")"

# Function to remove secret lines from a file
remove_secrets() {
  local file="$1"
  # Remove lines containing sensitive keywords
  sed -i '' '/openai api key/d; /github personal access token/d' "$file"
}

# Check if there are any changes
if git status --porcelain | grep .; then
  # Stage all changes
  git add -A
  
  # Find files (excluding auto_commit.sh) that contain secret keywords in their content
  secret_files=$(git diff --cached --name-only -- ':!auto_commit.sh' | while read file; do
    if [ -f "$file" ] && grep -Ei "openai api key|github personal access token" "$file" >/dev/null; then
      echo "$file"
    fi
  done)
  
  # If secrets are detected, remove secret lines and restage the files
  if [ -n "$secret_files" ]; then
    echo "Secrets detected in the following files: $secret_files"
    echo "Removing lines containing secrets..."
    for f in $secret_files; do
      remove_secrets "$f"
      git add "$f"
    done
    # Re-check for secrets after removal
    if git diff --cached -- ':!auto_commit.sh' | grep -Ei "openai api key|github personal access token" >/dev/null; then
      echo "Secrets still detected after attempted removal. Aborting commit."
      git reset
      exit 1
    fi
  fi
  
  # Commit with timestamp and push to 'main'
  git commit -m "Auto commit $(date '+%Y-%m-%d %H:%M:%S')"
  git push origin main
fi
