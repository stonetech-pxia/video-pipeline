#!/usr/bin/env python3
"""Write the message that asks the Shot Director for one chunk.

Everything the director needs is already in the chunk plan; this only wraps it
in the constraints that make a chunk mergeable -- the window the plan fixed, the
beats it must cover, and local shot numbering.

Usage: build_chunk_message.py <chunk-plan.json> <chunk_id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

TEMPLATE = """Produce Shot IR chunk {chunk_id} for the story slice below, following the ai-storyboard-director skill in Shot IR mode.

Return only JSON conforming to schemas/shot-ir-chunk.schema.json. Nothing else: no prose, no commentary.
Write Chinese text directly as UTF-8 characters; never escape it as \\uXXXX.

Emit exactly these top-level fields and no others: schema_version, chunk_id, status, start, end, shots, continuity_exit_state, warnings, errors.

Hard constraints for this chunk:

- The time window is fixed. shots[0].start must be {start}, the shots must be contiguous with no gaps, and the last shot must end exactly at {end}.
- Cover every beat in this chunk: {beats}. Every beat must appear in some shot's source_beat_ids, and no other beat may.
- A shot draws its beats from one scene only. {entry}
- Number your shots locally inside this chunk, for example {chunk_id}-01, {chunk_id}-02. Global numbering is assigned when chunks are merged.
- Do not emit film-level fields: aspect_ratio, visual_style, overall_soundscape, music, duration. Those belong to the film head, not to a chunk.
- Every shot needs characters_in_frame, and every shot needs one entry in continuity_exit_state.by_shot.
- Set chunk_id to {chunk_id}, start to {start}, end to {end}, schema_version to 1.1.

The story slice for this chunk:

{slice}
"""

MID_SCENE = "This chunk starts inside a scene; the previous chunk's last shot is the only handover."
ON_BOUNDARY = "This chunk starts on a scene boundary."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("chunk_id")
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    chunk = next((item for item in plan.get("chunks", [])
                  if item.get("chunk_id") == args.chunk_id), None)
    if chunk is None:
        print(f"the plan declares no chunk {args.chunk_id}", file=sys.stderr)
        return 2

    sys.stdout.write(TEMPLATE.format(
        chunk_id=chunk["chunk_id"],
        start=chunk["start"],
        end=chunk["end"],
        beats=", ".join(chunk["beat_ids"]),
        entry=MID_SCENE if chunk["entry_mid_scene"] else ON_BOUNDARY,
        slice=json.dumps(chunk, ensure_ascii=False, indent=2),
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
