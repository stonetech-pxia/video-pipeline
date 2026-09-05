#!/usr/bin/env python3
"""Validate one frame-design chunk against the resolved Shot IR chunk it covers.

Catches a bad chunk while it is still cheap to redo, before the merge. What
needs the whole film -- global segment numbering, seams between chunks -- stays
in merge_frames.py.

A chunk cannot see the shot before its first one, so the check that a scene
opening restates what survived the change would go quiet at every seam. Pass
the previous chunk with --previous and that shot is spliced in ahead of this
chunk's, which is all the check needs to fire there too.

Usage: validate_frame_chunk.py <resolved-shot-chunk.json> <frame-chunk.json | ->
                               [--previous <previous-resolved-shot-chunk.json>]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_frame_design import (  # noqa: E402
    validate as validate_semantics,
    with_previous_shot,
)

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
EXTERNAL = "frame-design-output.schema.json#/"


def load(path: Path | None) -> dict[str, Any]:
    raw = sys.stdin.read() if path is None else path.read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("top-level JSON value must be an object")
    return value


def inline(node: Any, base: dict[str, Any]) -> Any:
    """Splice references to the frame-design schema into the chunk schema.

    Resolving them at load time keeps one definition of a segment while staying
    off the resolver API, which changed shape across jsonschema versions and
    differs between this checkout and the openclaw runtime.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(EXTERNAL):
            target: Any = base
            for part in ref[len(EXTERNAL):].split("/"):
                target = target[part]
            return inline(target, base)
        return {key: inline(value, base) for key, value in node.items()}
    if isinstance(node, list):
        return [inline(item, base) for item in node]
    return node


def schema_errors(chunk: dict[str, Any]) -> list[str]:
    base = json.loads((SCHEMAS / "frame-design-output.schema.json").read_text(encoding="utf-8"))
    schema = json.loads((SCHEMAS / "frame-design-chunk.schema.json").read_text(encoding="utf-8"))
    schema["$defs"] = base["$defs"]
    validator = Draft202012Validator(inline(schema, base))
    return [
        f"{'.'.join(str(part) for part in item.absolute_path)}: {item.message}"
        for item in validator.iter_errors(chunk)
    ]


def check_window(chunk: dict[str, Any], shot_chunk: dict[str, Any]) -> list[str]:
    errors = []
    if chunk.get("chunk_id") != shot_chunk.get("chunk_id"):
        errors.append(
            f"the artifact says chunk_id {chunk.get('chunk_id')}, but the shots it covers "
            f"belong to {shot_chunk.get('chunk_id')}"
        )
    if (chunk.get("start"), chunk.get("end")) != (shot_chunk.get("start"), shot_chunk.get("end")):
        errors.append(
            f"the chunk claims {chunk.get('start')}-{chunk.get('end')}, but its shots run "
            f"{shot_chunk.get('start')}-{shot_chunk.get('end')}"
        )
    return errors


def validate(shot_chunk: dict[str, Any], chunk: dict[str, Any],
             previous: dict[str, Any] | None = None) -> list[str]:
    errors = schema_errors(chunk)
    if errors:
        return errors
    if chunk.get("status") != "complete" and not chunk.get("errors"):
        errors.append(f"a {chunk.get('status')} chunk must carry at least one error")
    errors.extend(check_window(chunk, shot_chunk))
    errors.extend(
        f"{item['path']}: {item['message']} [{item['code']}]"
        for item in validate_semantics(chunk, with_previous_shot(shot_chunk, previous))
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shot_chunk", help="the resolved Shot IR chunk these segments cover")
    parser.add_argument("artifact", help="path to the frame-design chunk, or - to read stdin")
    parser.add_argument("--previous", help="the previous resolved Shot IR chunk, for the seam check")
    args = parser.parse_args()
    try:
        errors = validate(
            load(Path(args.shot_chunk)),
            load(None if args.artifact == "-" else Path(args.artifact)),
            load(Path(args.previous)) if args.previous else None,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
