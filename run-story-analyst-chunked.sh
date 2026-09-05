#!/usr/bin/env bash
# Run the WSL openclaw story-analyst over a long narrative in bounded passes.
#
# Pass 0 asks for a story plan: the scene spine, the entity registry, and the
# chunk grouping the agent itself chooses. Each chunk is then a separate turn in
# the same session, so the agent keeps continuity while no single reply has to
# carry the whole film. Every pass is validated as it arrives and retried on its
# own, so a bad pass costs one chunk instead of the whole artifact.
#
# Usage: ./run-story-analyst-chunked.sh <envelope.json> [out.json]
set -euo pipefail
export MSYS_NO_PATHCONV=1

in="$1"
out="${2:-story-ir.json}"
max="${MAX_ATTEMPTS:-3}"

stamp="$(date +%Y%m%d-%H%M%S-%N)"
key="chunked-$stamp"
dir="/home/openclaw/.openclaw/tmp/claude-runs/$stamp"
local_dir="$(mktemp -d)"
workspace="/home/openclaw/.openclaw/workspace-story-analyst"
skill="$workspace/skills/script-chunked-breakdown"

wsl() { wsl.exe -d OpenClawGateway -- "$@"; }
put() { wsl bash -c "cat > '$1'"; }

# pass <kind> <name> <first-message-file> -> $local_dir/<name>.json
pass() {
  local kind="$1" name="$2" msg="$3" report
  for attempt in $(seq 1 "$max"); do
    echo "--- $name (attempt $attempt/$max) ---" >&2
    if ! wsl openclaw agent --agent story-analyst --session-key "$key" \
        --message-file "$msg" --timeout 900 --json \
      | wsl python3 /home/openclaw/.openclaw/bin/extract_ir.py > "$local_dir/$name.json"; then
      report='{"valid": false, "errors": ["the reply contained no parseable JSON artifact"]}'
    else
      put "$dir/$name.json" < "$local_dir/$name.json"
      local against=()
      [ "$kind" = chunk ] && against=(--plan "$dir/plan.json")
      report="$(wsl python3 "$skill/scripts/validate_pass.py" "$kind" "$dir/$name.json" "${against[@]}" || true)"
    fi

    printf '%s' "$report" | grep -q '"valid": true' && return 0

    echo "$report" >&2
    [ "$attempt" -eq "$max" ] && return 1

    msg="$dir/retry-$name-$attempt.txt"
    {
      printf 'That %s failed validation. Return the corrected, complete %s artifact as JSON and nothing else. Fix exactly these errors:\n\n' "$kind" "$kind"
      printf '%s\n' "$report"
    } | put "$msg"
  done
}

wsl bash -c "mkdir -p '$dir'"

# ---- pass 0: plan -------------------------------------------------------
{
  printf 'Produce the story plan for the envelope below, following the `script-chunked-breakdown` skill. Return only JSON conforming to schemas/story-plan.schema.json — the scene spine, the entity registry, and your chunk grouping. Do not write beats yet.\n\n'
  cat "$in"
} | put "$dir/ask-plan.txt"

pass plan plan "$dir/ask-plan.txt" || { echo "plan never validated" >&2; exit 1; }

chunk_ids="$(wsl python3 -c "
import json
p = json.load(open('$dir/plan.json'))
print(','.join(c['id'] for c in p['chunks']))
")"
echo "plan ok: $(wsl python3 -c "
import json; print(len(json.load(open('$dir/plan.json'))['scenes']))") scenes, chunks $chunk_ids" >&2

# ---- pass N: one chunk per turn ----------------------------------------
files=()
for chunk in $(tr ',' ' ' <<<"$chunk_ids"); do
  printf 'Now produce chunk %s. Return only JSON conforming to schemas/story-ir-chunk.schema.json, covering only that chunk'"'"'s scenes. Continue beat, dialogue, constraint, and marker IDs from where the previous chunk stopped; never restart numbering.\n' \
    "$chunk" | put "$dir/ask-$chunk.txt"
  pass chunk "$chunk" "$dir/ask-$chunk.txt" || { echo "chunk $chunk never validated" >&2; exit 1; }
  files+=("$dir/$chunk.json")
done

# ---- merge + validate the whole film ------------------------------------
echo "--- merge ---" >&2
wsl python3 "$skill/scripts/merge_chunks.py" "$dir/plan.json" "${files[@]}" > "$out"
put "$dir/merged.json" < "$out"

echo "--- validate merged ---" >&2
wsl bash -c "cd '$workspace' && python3 skills/script-structural-breakdown/scripts/validate_output.py '$dir/merged.json'"
