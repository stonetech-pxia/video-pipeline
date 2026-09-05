#!/usr/bin/env bash
# Run the WSL openclaw story-analyst agent (GLM-5.3-Flash) on one envelope.
# Fresh session key each run => no prior context.
# Usage: ./run-story-analyst.sh <envelope.json> [out.json]
set -euo pipefail
export MSYS_NO_PATHCONV=1

in="$1"
out="${2:-story-ir.json}"
stamp="$(date +%Y%m%d-%H%M%S-%N)"
remote="/home/openclaw/.openclaw/tmp/claude-runs/${stamp}.json"

wsl.exe -d OpenClawGateway -- bash -c "mkdir -p /home/openclaw/.openclaw/tmp/claude-runs && cat > '$remote'" < "$in"

wsl.exe -d OpenClawGateway -- openclaw agent \
  --agent story-analyst \
  --session-key "run-$stamp" \
  --message-file "$remote" \
  --timeout 600 --json \
| wsl.exe -d OpenClawGateway -- python3 /home/openclaw/.openclaw/bin/extract_ir.py > "$out"

echo "wrote $out"
