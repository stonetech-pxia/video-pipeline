#!/usr/bin/env bash
# Design a film's frames one chunk at a time through the WSL openclaw frame-designer.
#
# Mirrors run-shot-director-chunked.sh. Each chunk is its own session: the
# message carries the packed segment skeleton, the shots it covers, the
# reference images its subjects resolve to, and the state the previous chunk's
# last shot left behind. A chunk that fails validation is retried on its own.
#
# Usage: ./run-frame-designer-chunked.sh <story-ir.json> <chunk-dir> <out-dir> [chunk_id ...]
#        <chunk-dir> holds the director's K*.json and its assets.json.
#        With no chunk ids, every chunk file in the directory is designed, in order.
set -euo pipefail
export MSYS_NO_PATHCONV=1

story="$1"
chunks="$2"
out="$3"
shift 3
max="${MAX_ATTEMPTS:-3}"

stamp="$(date +%Y%m%d-%H%M%S)"
dir="/home/openclaw/.openclaw/tmp/frame-chunks/$stamp"
frame_ws="/home/openclaw/.openclaw/workspace-frame-designer"
pipe_ws="/home/openclaw/.openclaw/workspace-video-pipeline"

wsl() { wsl.exe -d OpenClawGateway -- "$@"; }
put() { wsl bash -c "cat > '$1'"; }

mkdir -p "$out"
wsl bash -c "mkdir -p '$dir'"
put "$dir/story.json" < "$story"
put "$dir/assets.json" < "$chunks/assets.json"

ids=("$@")
if [ ${#ids[@]} -eq 0 ]; then
  mapfile -t ids < <(ls "$chunks" | sed -n 's/^\(K[0-9]*\)\.json$/\1/p' | sort -V)
fi
echo "chunks: ${ids[*]}" >&2

previous=""
for id in "${ids[@]}"; do
  put "$dir/$id.json" < "$chunks/$id.json"

  # The designer needs scene_id and location_id on every shot; --no-record keeps
  # the registry as the director left it.
  wsl bash -c "cd '$pipe_ws' && python3 scripts/resolve_assets.py '$dir/$id.json' '$dir/story.json' \
      '$dir/assets.json' --no-record > '$dir/$id-resolved.json'"

  prev_arg=""
  [ -n "$previous" ] && prev_arg="--previous '$dir/$previous-resolved.json'"
  wsl bash -c "cd '$frame_ws' && python3 scripts/build_frame_message.py '$dir/$id-resolved.json' \
      '$dir/assets.json' $prev_arg --resolved-path '$dir/$id-resolved.json' \
      --candidate-path '$dir/candidate-$id.json' > '$dir/ask-$id.txt'"
  wsl cat "$dir/ask-$id.txt" > "$out/ask-$id.txt"

  msg="$dir/ask-$id.txt"
  ok=0
  for attempt in $(seq 1 "$max"); do
    echo "--- $id (attempt $attempt/$max) ---" >&2
    wsl bash -c "rm -f '$dir/candidate-$id.json'"
    reply="$(wsl openclaw agent --agent frame-designer --session-key "frame-$stamp-$id" \
        --message-file "$msg" --timeout 900 --json || true)"

    # The artifact is the file the designer validated, not the reply it typed
    # afterwards. Retyping it re-composes the JSON from scratch, which drops
    # text the checker approved and has leaked another language into a prompt.
    if wsl bash -c "test -s '$dir/candidate-$id.json'"; then
      wsl cat "$dir/candidate-$id.json" > "$out/frame-$id.json"
      artifact="$dir/candidate-$id.json"
    elif printf '%s' "$reply" | wsl python3 /home/openclaw/.openclaw/bin/extract_ir.py > "$out/frame-$id.json"; then
      put "$dir/frame-$id.json" < "$out/frame-$id.json"
      artifact="$dir/frame-$id.json"
      echo "note: $id answered without writing its candidate file; fell back to the reply" >&2
    else
      artifact=""
    fi

    if [ -z "$artifact" ]; then
      report='{"valid": false, "errors": ["no artifact: write it to the candidate path the message gives you, validate it there, and answer with that file"]}'
    else
      report="$(wsl bash -c "cd '$frame_ws' && python3 scripts/validate_frame_chunk.py \
          '$dir/$id-resolved.json' '$artifact' $prev_arg" || true)"
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
  previous="$id"
  echo "$id ok" >&2
done

echo "--- done; artifacts in $out ---" >&2
