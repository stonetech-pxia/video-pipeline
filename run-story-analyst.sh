#!/usr/bin/env bash
# Run the WSL openclaw story-analyst agent (GLM-5.3-Flash) on one envelope.
#
# Attempt 1 starts from a fresh session key, so it carries no prior context.
# If the artifact fails schema validation, the validator's errors are handed
# back to the same session and the agent repairs its own output, up to
# MAX_ATTEMPTS times.
#
# Usage: ./run-story-analyst.sh <envelope.json> [out.json]
set -euo pipefail
export MSYS_NO_PATHCONV=1

in="$1"
out="${2:-story-ir.json}"
max="${MAX_ATTEMPTS:-3}"

stamp="$(date +%Y%m%d-%H%M%S-%N)"
key="run-$stamp"
dir="/home/openclaw/.openclaw/tmp/claude-runs"
msg="$dir/$stamp-1.json"
remote_out="$dir/$stamp-out.json"
workspace="/home/openclaw/.openclaw/workspace-story-analyst"

wsl() { wsl.exe -d OpenClawGateway -- "$@"; }

wsl bash -c "mkdir -p '$dir' && cat > '$msg'" < "$in"

for attempt in $(seq 1 "$max"); do
  echo "--- attempt $attempt/$max ---" >&2

  wsl openclaw agent \
    --agent story-analyst \
    --session-key "$key" \
    --message-file "$msg" \
    --timeout 900 --json \
  | wsl python3 /home/openclaw/.openclaw/bin/extract_ir.py > "$out" || {
      echo "could not extract JSON from the reply" >&2
      [ "$attempt" -eq "$max" ] && exit 1
      msg="$dir/$stamp-$((attempt + 1)).txt"
      printf 'Your reply did not contain a parseable JSON artifact. Return only the complete Story IR JSON object and nothing else: no prose, no validator report, no commentary.\n' \
        | wsl bash -c "cat > '$msg'"
      continue
    }

  wsl bash -c "cat > '$remote_out'" < "$out"
  report="$(wsl bash -c "cd '$workspace' && python3 skills/script-structural-breakdown/scripts/validate_output.py '$remote_out'" || true)"

  if printf '%s' "$report" | grep -q '"valid": true'; then
    echo "wrote $out (valid, attempt $attempt)"
    exit 0
  fi

  echo "$report" >&2
  [ "$attempt" -eq "$max" ] && break

  msg="$dir/$stamp-$((attempt + 1)).txt"
  {
    printf 'The Story IR you just returned failed validation. Fix exactly these errors and return the corrected, complete JSON artifact — the whole thing, not a patch:\n\n'
    printf '%s\n' "$report"
  } | wsl bash -c "cat > '$msg'"
done

echo "still invalid after $max attempts; last artifact left in $out" >&2
exit 1
