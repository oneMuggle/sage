#!/bin/bash

MAX_LINES=$(jq -r '.global.maxFileLines' architecture-policy.json)

echo "Files exceeding $MAX_LINES lines:"
find src backend electron -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.py" \) | while read file; do
  lines=$(wc -l < "$file")
  if [ "$lines" -gt "$MAX_LINES" ]; then
    over=$((lines - MAX_LINES))
    printf "  %-50s %5d lines (+%d)\n" "$file" "$lines" "$over"
  fi
done

echo ""
echo "Distribution:"
find src backend electron -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.py" \) | xargs wc -l | awk '
  $1 <= 200 { under200++ }
  $1 > 200 && $1 <= 400 { under400++ }
  $1 > 400 && $1 <= 800 { under800++ }
  $1 > 800 { over800++ }
  END {
    printf "  0-200 lines:   %4d files\n", under200
    printf "  200-400 lines: %4d files\n", under400
    printf "  400-800 lines: %4d files\n", under800
    printf "  800+ lines:    %4d files\n", over800
  }'
