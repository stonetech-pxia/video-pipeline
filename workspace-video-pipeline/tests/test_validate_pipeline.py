from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_pipeline.py"
SPEC = importlib.util.spec_from_file_location("validate_pipeline", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class PipelineValidatorTests(unittest.TestCase):
    def valid_story(self):
        return {
            "schema_version": "2.0",
            "status": "complete",
            "duration": 30,
            "scenes": [
                {
                    "id": "S01",
                    "slugline": "INT. ROOM - NIGHT",
                    "location_id": "L01",
                    "time_of_day": "night",
                    "duration_budget": 30,
                    "beat_ids": ["B01"],
                    "exit_state": "A is still waiting.",
                }
            ],
            "characters": [
                {"id": "C01", "name": "A", "wardrobe": "grey coat", "description": "Waiting."}
            ],
            "locations": [{"id": "L01", "name": "Room"}],
            "props": [],
            "beats": [
                {
                    "id": "B01",
                    "scene_id": "S01",
                    "action": "A waits",
                    "emotion": "restless",
                    "entity_ids": ["C01"],
                    "dialogue_ids": [],
                }
            ],
            "dialogue": [],
            "continuity_constraints": [],
            "transition_markers": [],
            "locked_constraints": [],
            "ambiguities": [],
        }

    def valid_prompt(self):
        return (
            "integrated_multimodal_description: [Shot 1] "
            + validator.FIRST_FRAME_DIRECTIVE
            + " 主角身份和外观参考 <Picture 1>，她抬头。\n\n"
            "overall_soundscape: Room tone.\n\n"
            "non_diegetic_music: N/A"
        )

    def valid_package(self):
        return {
            "segment_id": "SEG001",
            "shot_id": "S01",
            "start": 0,
            "end": 5,
            "local_duration": 5,
            "prompt_schema": "unified_multimodal",
            "execution_node": "MiniMax H3 Unified to Video",
            "unified_controls": {"entry_source": "resolved_first_frame", "last_frame_target": None, "reference_media": ["REF01"]},
            "prompt": self.valid_prompt(),
            "media_mapping": {
                "entry_frame": "FF01",
                "entry_frame_source_type": "resolved_media",
                "runtime_entry_binding": None,
                "last_frame_target": None,
                "expected_actual_tail_frame": None,
                "reference_media": ["REF01"],
                "reference_bindings": [{"label": "Picture 1", "media_id": "REF01", "role": "character_reference", "preserve": ["identity"], "do_not_copy": ["background"]}],
            },
        }

    def valid_draft_prompt(self):
        package = self.valid_package()
        controls = package.pop("unified_controls")
        controls["entry_source"] = "planned_first_frame"
        mapping = package.pop("media_mapping")
        mapping["entry_frame_source_type"] = "planned_media"
        mapping["unresolved_media_ids"] = ["FF01", "REF01"]
        package["planned_controls"] = controls
        package["symbolic_media_mapping"] = mapping
        return package

    def valid_frame(self, path: str):
        continuity = {
            "is_same_shot": False,
            "continuous_action": False,
            "continuous_camera": False,
            "same_scene": True,
            "same_framing": False,
            "same_camera_position": False,
            "same_time": True,
            "same_visual_focus": True,
            "requires_recomposition": True,
            "change_triggers": ["shot"],
            "decision": "generate_new_first_frame",
        }
        refs = {"character_reference_ids": [], "location_reference_ids": [], "style_reference_ids": [], "video_reference_ids": [], "audio_reference_ids": []}
        media = {
            "id": "FF01",
            "type": "frame",
            "role": "first_frame",
            "status": "resolved",
            "source_type": "uploaded",
            "source_job": None,
            "related_segments": ["SEG001"],
            "use_for": ["entry_anchor"],
            "entity_bindings": {"character_ids": [], "location_ids": []},
            "provenance": {"source_type": "uploaded", "source_id": None},
            "path": path,
        }
        return {
            "schema_version": "1.2",
            "status": "complete",
            "segment_plan": [{"segment_id": "SEG001", "shot_id": "S01", "previous_segment_id": None, "start": 0, "end": 5, "duration": 5, "entry_strategy": "new_first_frame", "entry_frame_source": "FF01", "runtime_entry_dependency": None, "exit_frame_required": False, "last_frame_target_media_id": None, "actual_tail_frame_media_id": None, "reference_strategy": refs, "continuity_decision": continuity, "reason": "scene entry"}],
            "frame_plan": [{"segment_id": "SEG001", "first_frame_media_id": "FF01", "last_frame_target_media_id": None, "actual_tail_frame_media_id": None, "reference_media_ids": [], "generate_first_frame": False, "generate_last_frame_target": False, "capture_actual_tail_frame": False}],
            "image_jobs": [],
            "media_manifest": {"status": "ready_for_compile", "supports_mixed_keyframes_and_references": True, "media": [media]},
            "warnings": [],
            "errors": [],
        }

    def test_story_rejects_legacy_generation_mode(self):
        story = self.valid_story()
        story["generation_mode"] = "I2VA"
        codes = {item["code"] for item in validator.validate_story(story)}
        self.assertIn("legacy_generation_mode", codes)
        self.assertIn("schema_violation", codes)

    def test_story_rejects_beat_outside_any_scene(self):
        story = self.valid_story()
        story["beats"].append(
            {
                "id": "B02",
                "scene_id": "S01",
                "action": "A stands",
                "emotion": None,
                "entity_ids": ["C01"],
                "dialogue_ids": [],
            }
        )
        self.assertIn("beat_without_scene", {item["code"] for item in validator.validate_story(story)})

    def test_story_rejects_unknown_scene_reference(self):
        story = self.valid_story()
        story["beats"][0]["scene_id"] = "S99"
        self.assertIn("unknown_beat_scene", {item["code"] for item in validator.validate_story(story)})

    def test_story_rejects_scene_claiming_unknown_beat(self):
        story = self.valid_story()
        story["scenes"][0]["beat_ids"] = ["B01", "B99"]
        self.assertIn("unknown_scene_beat", {item["code"] for item in validator.validate_story(story)})

    def test_unified_package_accepts_first_frame_and_reference(self):
        segment = {"segment_id": "SEG001", "shot_id": "S01", "start": 0, "end": 5, "entry_strategy": "new_first_frame", "entry_frame_source": "FF01"}
        media = {"REF01": {"id": "REF01", "status": "resolved"}}
        self.assertEqual(validator.validate_unified_package(self.valid_package(), segment, media), [])

    def test_unified_package_rejects_legacy_alignment(self):
        segment = {"segment_id": "SEG001", "shot_id": "S01", "start": 0, "end": 5, "entry_strategy": "new_first_frame", "entry_frame_source": "FF01"}
        package = self.valid_package()
        package["prompt"] = "For the target video, at 0.00 seconds into the target video\n" + self.valid_prompt()
        codes = {item["code"] for item in validator.validate_unified_package(package, segment, {"REF01": {"status": "resolved"}})}
        self.assertIn("legacy_prompt_syntax", codes)
        self.assertIn("unified_prompt_start", codes)

    def test_draft_compile_accepts_unresolved_symbolic_media(self):
        frame = self.valid_frame("/not-resolved-yet.png")
        frame["media_manifest"]["status"] = "draft"
        frame["media_manifest"]["media"][0]["status"] = "pending"
        frame["media_manifest"]["media"].append({"id": "REF01", "status": "pending", "role": "character_reference"})
        value = {
            "schema_version": "1.0",
            "status": "draft",
            "draft_video_prompts": [self.valid_draft_prompt()],
            "pending_media_ids": ["FF01", "REF01"],
            "errors": [],
        }
        self.assertEqual(validator.validate_draft_compile(value, frame, None), [])

    def test_draft_compile_rejects_missing_pending_media(self):
        frame = self.valid_frame("/not-resolved-yet.png")
        frame["media_manifest"]["status"] = "draft"
        frame["media_manifest"]["media"][0]["status"] = "pending"
        frame["media_manifest"]["media"].append({"id": "REF01", "status": "pending", "role": "character_reference"})
        value = {
            "schema_version": "1.0",
            "status": "draft",
            "draft_video_prompts": [self.valid_draft_prompt()],
            "pending_media_ids": ["FF01"],
            "errors": [],
        }
        self.assertIn("draft_pending_media", {item["code"] for item in validator.validate_draft_compile(value, frame, None)})

    def test_media_gate_proves_local_file_exists(self):
        with tempfile.NamedTemporaryFile() as handle:
            self.assertEqual(validator.validate_media(self.valid_frame(handle.name), None), [])

    def test_media_gate_rejects_missing_local_file(self):
        codes = {item["code"] for item in validator.validate_media(self.valid_frame("/definitely/missing/media.png"), None)}
        self.assertIn("asset_not_readable", codes)

    def test_validation_gate_matches_compile_report_and_packages(self):
        packages = {"packages": [self.valid_package()]}
        with tempfile.TemporaryDirectory() as directory:
            packages_path = Path(directory) / "packages.json"
            packages_path.write_text(json.dumps(packages), encoding="utf-8")
            report = {"stage": "compile", "status": "PASS", "report_id": "a" * 64, "artifact_hashes": {"artifact": validator.file_hash(packages_path)}, "errors": [], "warnings": []}
            value = {
                "schema_version": "1.3",
                "status": "PASS",
                "deterministic_gate": {"status": "PASS", "report_id": "a" * 64},
                "error_class": [],
                "errors": [],
                "warnings": [],
                "segment_checks": [{"segment_id": "SEG001", "source_fidelity_valid": True, "unified_syntax_valid": True, "entry_strategy_valid": True, "frame_link_valid": True, "reference_bundle_valid": True, "runtime_tail_dependency_valid": True, "continuation_prompt_valid": True, "errors": [], "warnings": []}],
                "validated_packages": packages["packages"],
            }
            self.assertEqual(validator.validate_validation(value, packages, report, packages_path), [])

    def test_validation_gate_rejects_stale_report(self):
        packages = {"packages": [self.valid_package()]}
        with tempfile.TemporaryDirectory() as directory:
            packages_path = Path(directory) / "packages.json"
            packages_path.write_text(json.dumps(packages), encoding="utf-8")
            value = {"schema_version": "1.3", "status": "FAIL", "deterministic_gate": {"status": "PASS", "report_id": "b" * 64}, "error_class": ["FORMAT"], "errors": [{"code": "x", "path": "", "message": "x", "owner": "h3-validator", "retryable": True}], "warnings": [], "segment_checks": [{"segment_id": "SEG001", "source_fidelity_valid": False, "unified_syntax_valid": True, "entry_strategy_valid": True, "frame_link_valid": True, "reference_bundle_valid": True, "runtime_tail_dependency_valid": True, "continuation_prompt_valid": True, "errors": [{"code": "x", "path": "", "message": "x", "owner": "h3-validator", "retryable": True}], "warnings": []}], "validated_packages": []}
            report = {"stage": "compile", "status": "PASS", "report_id": "a" * 64, "artifact_hashes": {"artifact": "0" * 64}, "errors": [], "warnings": []}
            codes = {item["code"] for item in validator.validate_validation(value, packages, report, packages_path)}
            self.assertIn("deterministic_report_mismatch", codes)
            self.assertIn("stale_deterministic_report", codes)

    def test_result_gate_accepts_structured_startup_failure(self):
        result = {
            "schema_version": "1.0",
            "status": "BLOCKED",
            "failed_stage": "story",
            "agent_id": "story-analyst",
            "failure_kind": "subagent_start_failed",
            "errors": [{"code": "MODEL_ROUTE_UNAVAILABLE", "path": "", "message": "Configured model route is unavailable.", "retryable": True}],
            "warnings": [],
            "last_valid_artifacts": {},
            "result": None,
        }
        self.assertEqual(validator.validate_result(result), [])

    def test_result_gate_rejects_startup_failure_without_agent(self):
        result = {
            "schema_version": "1.0",
            "status": "BLOCKED",
            "failed_stage": "story",
            "agent_id": None,
            "failure_kind": "subagent_start_failed",
            "errors": [{"code": "MODEL_ROUTE_UNAVAILABLE", "path": "", "message": "Configured model route is unavailable.", "retryable": True}],
            "warnings": [],
            "last_valid_artifacts": {},
            "result": None,
        }
        self.assertTrue(validator.validate_result(result))

    def test_result_gate_accepts_media_wait_with_draft_prompts(self):
        result = {
            "schema_version": "1.0",
            "status": "MEDIA_WAIT",
            "failed_stage": "media",
            "agent_id": None,
            "failure_kind": "media_wait",
            "errors": [],
            "warnings": [],
            "last_valid_artifacts": {},
            "result": {
                "draft_video_prompts": [self.valid_draft_prompt()],
                "image_jobs": [{"job_id": "JOB01", "prompt": "frame prompt", "negative_prompt": "bad frame", "output_media_id": "FF01", "status": "pending"}],
            },
        }
        self.assertEqual(validator.validate_result(result), [])

    def test_result_gate_rejects_media_wait_without_draft_prompts(self):
        result = {
            "schema_version": "1.0",
            "status": "MEDIA_WAIT",
            "failed_stage": "media",
            "agent_id": None,
            "failure_kind": "media_wait",
            "errors": [],
            "warnings": [],
            "last_valid_artifacts": {},
            "result": {"image_jobs": [{"job_id": "JOB01", "prompt": "frame prompt", "negative_prompt": "", "output_media_id": "FF01", "status": "pending"}]},
        }
        self.assertTrue(validator.validate_result(result))


if __name__ == "__main__":
    unittest.main()
