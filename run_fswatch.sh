#!/bin/bash
# Continuously monitor the project directory for any changes
# and invoke auto_commit.sh on each change.
fswatch -o "$(pwd)" | while read num; do
  ./auto_commit.sh
done
