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
            "shot_ids": ["S01"],
            "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}],
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
        refs = {"character_reference_ids": [], "location_reference_ids": [], "style_reference_ids": ["FF01"], "video_reference_ids": [], "audio_reference_ids": []}
        media = {
            "id": "FF01",
            "type": "image",
            "role": "style_reference",
            "status": "resolved",
            "source_type": "uploaded",
            "related_segments": ["SEG001"],
            "provenance": {"source_type": "uploaded"},
            "path": path,
        }
        return {
            "schema_version": "1.3",
            "status": "complete",
            "segment_plan": [{"segment_id": "SEG001", "scene_id": "SC01", "shot_ids": ["S01"], "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}], "previous_segment_id": None, "start": 0, "end": 5, "duration": 5, "entry_strategy": "references_only", "runtime_entry_dependency": None, "exit_frame_required": False, "actual_tail_frame_media_id": None, "reference_strategy": refs, "prompt": {"integrated_multimodal_description": "她抬头。", "overall_soundscape": "Room tone.", "non_diegetic_music": ""}, "reason": "scene entry"}],
            "media_manifest": {"status": "ready_for_compile", "media": [media]},
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
        segment = {"segment_id": "SEG001", "shot_ids": ["S01"], "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}], "start": 0, "end": 5, "entry_strategy": "new_first_frame", "entry_frame_source": "FF01"}
        media = {"REF01": {"id": "REF01", "status": "resolved"}}
        self.assertEqual(validator.validate_unified_package(self.valid_package(), segment, media), [])

    def test_unified_package_rejects_legacy_alignment(self):
        segment = {"segment_id": "SEG001", "shot_ids": ["S01"], "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}], "start": 0, "end": 5, "entry_strategy": "new_first_frame", "entry_frame_source": "FF01"}
        package = self.valid_package()
        package["prompt"] = "For the target video, at 0.00 seconds into the target video\n" + self.valid_prompt()
        codes = {item["code"] for item in validator.validate_unified_package(package, segment, {"REF01": {"status": "resolved"}})}
        self.assertIn("legacy_prompt_syntax", codes)
        self.assertIn("unified_prompt_start", codes)

    def test_unified_package_rejects_reassigned_shots(self):
        segment = {"segment_id": "SEG001", "shot_ids": ["S01", "S02"],
                   "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0},
                                     {"prompt_shot_index": 2, "shot_id": "S02", "local_start": 3}],
                   "start": 0, "end": 5, "entry_strategy": "references_only"}
        codes = {item["code"] for item in validator.validate_unified_package(self.valid_package(), segment, {"REF01": {"status": "resolved"}})}
        self.assertIn("segment_mapping", codes)

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

    def test_story_gate_rejects_budgets_that_miss_the_total(self):
        story = self.valid_story()
        story["scenes"][0]["duration_budget"] = story["scenes"][0]["duration_budget"] + 5
        codes = {item["code"] for item in validator.validate_story(story)}
        self.assertIn("duration_budget_mismatch", codes)

    def test_shot_gate_rejects_a_shot_longer_than_one_generatable_piece(self):
        labels = {"boundary_type": "shot_change", "camera_continuity": "changed",
                  "action_continuity": "discontinuous", "framing_continuity": "changed",
                  "scene_continuity": "scene_change", "recomposition_needed": True}
        shot_ir = {"schema_version": "1.1", "status": "complete", "duration": 20,
                   "shots": [{"id": "S01", "start": 0, "end": 20, "source_beat_ids": [],
                              "dialogue_ids": [], **labels}]}
        codes = {item["code"] for item in validator.validate_shot(shot_ir, None)}
        self.assertIn("shot_too_long", codes)

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
                "total_duration": 10,
                "aspect_ratio": "16:9",
                "draft_video_prompts": [self.valid_draft_prompt()],
                "pending_media_ids": ["FF01"],
            },
        }
        self.assertEqual(validator.validate_result(result), [])

    def test_result_gate_rejects_a_render_target_that_drifted_from_shot_ir(self):
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
                "total_duration": 10,
                "aspect_ratio": "9:16",
                "draft_video_prompts": [self.valid_draft_prompt()],
                "pending_media_ids": ["FF01"],
            },
        }
        shot = {"aspect_ratio": "16:9", "duration": 10}
        codes = {item["code"] for item in validator.validate_result(result, shot)}
        self.assertIn("render_target_mismatch", codes)

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
            "result": {"total_duration": 10, "aspect_ratio": "16:9",
                       "pending_media_ids": ["FF01"]},
        }
        self.assertTrue(validator.validate_result(result))


if __name__ == "__main__":
    unittest.main()
