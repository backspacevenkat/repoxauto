#!/bin/bash
# Navigate to project root
cd "$(dirname "$0")"

# Function to remove secret lines from a file
remove_secrets() {
  local file="$1"
  # Remove lines containing sensitive keywords (supporting underscores and spaces)
  sed -i '' '/openai[_ ]*api[_ ]*key/d; /github[_ ]*personal[_ ]*access[_ ]*token/d' "$file"
}

# Check if there are any changes
if git status --porcelain | grep .; then
  # Stage all changes
  git add -A
  
  # Use an enhanced grep pattern for secrets, excluding auto_commit.sh
  if git diff --cached -- ':!auto_commit.sh' | grep -Ei "openai[_ ]*api[_ ]*key|github[_ ]*personal[_ ]*access[_ ]*token" >/dev/null; then
    echo "Secrets detected in staged changes. Removing secret lines..."
    secret_files=$(git diff --cached --name-only -- ':!auto_commit.sh')
    for f in $secret_files; do
      if [ -f "$f" ] && grep -Ei "openai[_ ]*api[_ ]*key|github[_ ]*personal[_ ]*access[_ ]*token" "$f" >/dev/null; then
        echo "Processing $f ..."
        remove_secrets "$f"
        git add "$f"
      fi
    done
    # Re-check for secrets after removal
    if git diff --cached -- ':!auto_commit.sh' | grep -Ei "openai[_ ]*api[_ ]*key|github[_ ]*personal[_ ]*access[_ ]*token" >/dev/null; then
      echo "Secrets still detected after attempted removal. Aborting commit."
      git reset
      exit 1
    fi
  fi
  
  # Commit with timestamp and push to 'main'
  git commit -m "Auto commit $(date '+%Y-%m-%d %H:%M:%S')"
  git push origin main
fi
