#!/usr/bin/env bash
# Direct a whole film one chunk at a time through the WSL openclaw shot-director.
#
# Each chunk is its own session: the plan hands it a self-contained story slice,
# so nothing depends on the director remembering the last one. A chunk that
# fails validation is retried on its own, and a bad chunk costs one chunk rather
# than the whole film. After each chunk validates, its shots are folded into the
# asset registry, so once every chunk is directed the registry is complete.
#
# Usage: ./run-shot-director-chunked.sh <story-ir.json> <out-dir> [chunk_id ...]
#        With no chunk ids, every chunk in the plan is directed.
set -euo pipefail
export MSYS_NO_PATHCONV=1

story="$1"
out="$2"
shift 2
max="${MAX_ATTEMPTS:-3}"

stamp="$(date +%Y%m%d-%H%M%S)"
dir="/home/openclaw/.openclaw/tmp/shot-chunks/$stamp"
shot_ws="/home/openclaw/.openclaw/workspace-shot-director"
pipe_ws="/home/openclaw/.openclaw/workspace-video-pipeline"

wsl() { wsl.exe -d OpenClawGateway -- "$@"; }
put() { wsl bash -c "cat > '$1'"; }

mkdir -p "$out"
wsl bash -c "mkdir -p '$dir'"
put "$dir/story.json" < "$story"

echo "--- plan ---" >&2
wsl bash -c "cd '$shot_ws' && python3 scripts/plan_chunks.py '$dir/story.json' > '$dir/plan.json'"
wsl cat "$dir/plan.json" > "$out/plan.json"

ids=("$@")
if [ ${#ids[@]} -eq 0 ]; then
  mapfile -t ids < <(wsl python3 -c "
import json
plan = json.load(open('$dir/plan.json'))
print('\n'.join(chunk['chunk_id'] for chunk in plan['chunks']))
")
fi
echo "chunks: ${ids[*]}" >&2

for id in "${ids[@]}"; do
  wsl bash -c "cd '$shot_ws' && python3 scripts/build_chunk_message.py '$dir/plan.json' '$id' > '$dir/ask-$id.txt'"
  msg="$dir/ask-$id.txt"
  ok=0

  for attempt in $(seq 1 "$max"); do
    echo "--- $id (attempt $attempt/$max) ---" >&2
    if ! wsl openclaw agent --agent shot-director --session-key "chunk-$stamp-$id" \
        --message-file "$msg" --timeout 900 --json \
      | wsl python3 /home/openclaw/.openclaw/bin/extract_ir.py > "$out/$id.json"; then
      report='{"valid": false, "errors": ["the reply contained no parseable JSON artifact; write Chinese directly as UTF-8, never as \\uXXXX escapes"]}'
    else
      put "$dir/$id.json" < "$out/$id.json"
      report="$(wsl bash -c "cd '$shot_ws' && python3 scripts/validate_chunk.py '$dir/plan.json' '$id' '$dir/$id.json'" || true)"
    fi

    if printf '%s' "$report" | grep -q '"valid": true'; then ok=1; break; fi

    echo "$report" >&2
    [ "$attempt" -eq "$max" ] && break

    msg="$dir/retry-$id-$attempt.txt"
    {
      printf 'That chunk failed validation. Return the corrected, complete chunk artifact as JSON and nothing else. Write Chinese directly as UTF-8; never escape it. Fix exactly these errors:\n\n'
      printf '%s\n' "$report"
    } | put "$msg"
  done

  [ "$ok" -eq 1 ] || { echo "chunk $id never validated" >&2; exit 1; }

  # Fold the validated chunk into the registry the reference images come from.
  wsl bash -c "cd '$pipe_ws' && python3 scripts/resolve_assets.py '$dir/$id.json' '$dir/story.json' '$dir/assets.json' > '$dir/$id-resolved.json'"
  wsl cat "$dir/assets.json" > "$out/assets.json"
  echo "$id ok" >&2
done

echo "--- done; artifacts in $out ---" >&2
