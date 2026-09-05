Return JSON only. Compile this approved single-segment fixture according to AGENTS.md and the installed h3-prompt-writing Skill.

Shot IR:
{
  "schema_version": "1.1",
  "status": "complete",
  "duration": 5,
  "aspect_ratio": "16:9",
  "visual_style": {"description": "cinematic realism"},
  "shots": [{
    "id": "S01",
    "start": 0,
    "end": 5,
    "source_beat_ids": ["B01"],
    "dramatic_purpose": "The woman notices a sound and looks up.",
    "framing": "medium shot",
    "angle": "eye level",
    "camera_position": "in front of the desk",
    "camera_motion": "slow push-in",
    "focus": "the woman",
    "blocking": "seated at the desk",
    "subject_action": "she pauses, hears the sound, and looks up",
    "visible_emotion": "alert curiosity",
    "environment": "quiet study",
    "lighting": "warm desk lamp",
    "dialogue_ids": [],
    "dialogue": "",
    "diegetic_audio": "soft room tone and a distant knock",
    "transition": "none",
    "segments": [],
    "boundary_type": "shot_change",
    "camera_continuity": "changed",
    "action_continuity": "discontinuous",
    "framing_continuity": "changed",
    "scene_continuity": "same_scene",
    "recomposition_needed": true
  }],
  "overall_soundscape": {"description": "quiet study, distant knock"},
  "music": {"description": "none"},
  "continuity_exit_state": {},
  "warnings": [],
  "errors": []
}

Frame Design:
{
  "schema_version": "1.2",
  "status": "complete",
  "segment_plan": [{
    "segment_id": "SEG001",
    "shot_ids": ["S01"],
    "shot_bindings": [{ "prompt_shot_index": 1, "shot_id": "S01", "local_start": 0 }],
    "previous_segment_id": null,
    "start": 0,
    "end": 5,
    "duration": 5,
    "entry_strategy": "new_first_frame",
    "entry_frame_source": "FF001",
    "runtime_entry_dependency": null,
    "exit_frame_required": false,
    "last_frame_target_media_id": null,
    "actual_tail_frame_media_id": null,
    "reference_strategy": {
      "character_reference_ids": ["REF001"],
      "location_reference_ids": [],
      "style_reference_ids": [],
      "video_reference_ids": [],
      "audio_reference_ids": []
    },
    "continuity_decision": {
      "is_same_shot": false,
      "continuous_action": false,
      "continuous_camera": false,
      "same_scene": true,
      "same_framing": false,
      "same_camera_position": false,
      "same_time": true,
      "same_visual_focus": true,
      "requires_recomposition": true,
      "change_triggers": ["shot"],
      "decision": "generate_new_first_frame"
    },
    "reason": "scene entry"
  }],
  "frame_plan": [{
    "segment_id": "SEG001",
    "first_frame_media_id": "FF001",
    "last_frame_target_media_id": null,
    "actual_tail_frame_media_id": null,
    "reference_media_ids": ["REF001"]
  }],
  "image_jobs": [],
  "media_manifest": {
    "status": "ready_for_compile",
    "media": [
      {
        "id": "FF001",
        "type": "frame",
        "role": "first_frame",
        "status": "resolved",
        "source_type": "uploaded",
        "source_job": null,
        "related_segments": ["SEG001"],
        "provenance": {"source_type": "uploaded", "source_id": "fixture-first"},
        "runtime_handle": "fixture://first-frame"
      },
      {
        "id": "REF001",
        "type": "image",
        "role": "character_reference",
        "status": "resolved",
        "source_type": "uploaded",
        "source_job": null,
        "related_segments": ["SEG001"],
        "provenance": {"source_type": "uploaded", "source_id": "fixture-character"},
        "runtime_handle": "fixture://character-reference"
      }
    ]
  },
  "warnings": [],
  "errors": []
}

Locked constraints:
- Preserve the woman's identity from REF001.
- Do not copy REF001 background, pose, or composition.
- The node-supplied FF001 is the exact opening image.
