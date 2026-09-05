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
            "schema_version": "1.1",
            "status": "complete",
            "duration": 30,
            "characters": [{"id": "C01", "name": "A"}],
            "locations": [],
            "props": [],
            "beats": [{"id": "B01", "start": 0, "end": 30, "action": "A waits"}],
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
            + " 主角身份和外观参考 <Picture 1>，但不要复制 <Picture 1> 的背景、构图和姿势。她抬头。\n\n"
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
            "provenance": {"source_type": "uploaded"},
            "path": path,
        }
        return {
            "schema_version": "1.2",
            "status": "complete",
            "segment_plan": [{"segment_id": "SEG001", "shot_ids": ["S01"], "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}], "previous_segment_id": None, "start": 0, "end": 5, "duration": 5, "entry_strategy": "new_first_frame", "entry_frame_source": "FF01", "runtime_entry_dependency": None, "exit_frame_required": False, "last_frame_target_media_id": None, "actual_tail_frame_media_id": None, "reference_strategy": refs, "continuity_decision": continuity, "reason": "scene entry"}],
            "frame_plan": [{"segment_id": "SEG001", "first_frame_media_id": "FF01", "last_frame_target_media_id": None, "actual_tail_frame_media_id": None, "reference_media_ids": []}],
            "image_jobs": [],
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

    def test_story_rejects_timed_beat_gap(self):
        story = self.valid_story()
        story["beats"] = [{"id": "B01", "start": 0, "end": 10}, {"id": "B02", "start": 11, "end": 30}]
        self.assertIn("beat_timeline_gap", {item["code"] for item in validator.validate_story(story)})

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


class PackedPromptTests(unittest.TestCase):
    """A segment covering several shots must carry exactly those cuts."""

    def bindings(self):
        return [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0},
                {"prompt_shot_index": 2, "shot_id": "S02", "local_start": 3},
                {"prompt_shot_index": 3, "shot_id": "S03", "local_start": 6}]

    def prompt(self, cuts=("00:03.000", "00:06.000")):
        body = "integrated_multimodal_description: [Shot 1] " + validator.FIRST_FRAME_DIRECTIVE + " 主角身份和外观参考 <Picture 1>，但不要复制 <Picture 1> 的背景、构图和姿势。她抬头。"
        for index, cut in enumerate(cuts, start=2):
            body += f" [Shot {index}] At {cut}, the camera cuts to a closer angle."
        return body + "\n\noverall_soundscape: Room tone.\n\nnon_diegetic_music: N/A"

    def packed(self, prompt=None, bindings=None):
        package = {
            "segment_id": "SEG001",
            "shot_ids": ["S01", "S02", "S03"],
            "shot_bindings": bindings if bindings is not None else self.bindings(),
            "start": 0, "end": 10, "local_duration": 10,
            "prompt_schema": "unified_multimodal",
            "execution_node": "MiniMax H3 Unified to Video",
            "unified_controls": {"entry_source": "resolved_first_frame", "last_frame_target": None, "reference_media": ["REF01"]},
            "prompt": prompt if prompt is not None else self.prompt(),
            "media_mapping": {
                "entry_frame": "FF01", "entry_frame_source_type": "resolved_media",
                "runtime_entry_binding": None, "last_frame_target": None,
                "expected_actual_tail_frame": None, "reference_media": ["REF01"],
                "reference_bindings": [{"label": "Picture 1", "media_id": "REF01", "role": "character_reference",
                                        "preserve": ["identity"], "do_not_copy": ["background"]}],
            },
        }
        segment = {"segment_id": "SEG001", "shot_ids": ["S01", "S02", "S03"],
                   "shot_bindings": package["shot_bindings"], "start": 0, "end": 10,
                   "entry_strategy": "new_first_frame", "entry_frame_source": "FF01"}
        media = {"FF01": {"id": "FF01", "status": "resolved"}, "REF01": {"id": "REF01", "status": "resolved"}}
        return package, segment, media

    def codes(self, package, segment, media):
        return {item["code"] for item in validator.validate_unified_package(package, segment, media)}

    def test_matching_cuts_are_accepted(self):
        self.assertEqual(validator.validate_unified_package(*self.packed()), [])

    def test_character_reference_without_do_not_copy_clause_is_rejected(self):
        stripped = self.prompt().replace("但不要复制 <Picture 1> 的背景、构图和姿势。", "")
        package, segment, media = self.packed(prompt=stripped)
        self.assertIn("do_not_copy_directive", self.codes(package, segment, media))

    def test_missing_shot_marker_is_rejected(self):
        package, segment, media = self.packed(prompt=self.prompt(cuts=("00:03.000",)))
        self.assertIn("shot_marker_sequence", self.codes(package, segment, media))

    def test_cut_at_wrong_time_is_rejected(self):
        package, segment, media = self.packed(prompt=self.prompt(cuts=("00:04.000", "00:06.000")))
        self.assertIn("shot_cut_timing", self.codes(package, segment, media))

    def test_extra_invented_cut_is_rejected(self):
        package, segment, media = self.packed(prompt=self.prompt(cuts=("00:03.000", "00:06.000", "00:08.000")))
        self.assertIn("shot_marker_sequence", self.codes(package, segment, media))

    def test_draft_path_shares_the_same_checks(self):
        package, segment, media = self.packed(prompt=self.prompt(cuts=("00:04.000", "00:06.000")))
        draft = {k: v for k, v in package.items() if k not in ("unified_controls", "media_mapping")}
        draft["planned_controls"] = package["unified_controls"]
        draft["symbolic_media_mapping"] = {**package["media_mapping"], "unresolved_media_ids": []}
        frame = {"segment_plan": [segment], "media_manifest": {"media": [
            {"id": "FF01", "status": "resolved", "role": "first_frame"},
            {"id": "REF01", "status": "resolved", "role": "character_reference"}]}}
        report = validator.validate_draft_compile(
            {"schema_version": "1.0", "status": "draft", "draft_video_prompts": [draft],
             "pending_media_ids": [], "errors": []}, frame, None)
        self.assertIn("shot_cut_timing", {item["code"] for item in report})


class ResultGateCrossChecks(unittest.TestCase):
    """COMPLETE results must be runnable: every package media arrives with a location."""

    def shot(self):
        return {"duration": 10, "aspect_ratio": "16:9", "visual_style": {"look": "cinematic"}}

    def packages(self):
        return {"packages": [{
            "segment_id": "SEG001",
            "media_mapping": {"entry_frame": "FF01", "last_frame_target": None,
                              "expected_actual_tail_frame": None, "reference_media": ["REF01"],
                              "runtime_entry_binding": None},
        }]}

    def result(self, **overrides):
        payload = {
            "total_duration": 10, "aspect_ratio": "16:9", "visual_style": {"look": "cinematic"},
            "packages": self.packages()["packages"],
            "resolved_media": [
                {"media_id": "FF01", "role": "first_frame", "status": "resolved", "location": "/tmp/ff01.png"},
                {"media_id": "REF01", "role": "character_reference", "status": "resolved", "location": "/tmp/ref01.png"},
            ],
            "execution_order": [{"order": 1, "segment_id": "SEG001", "depends_on": None}],
            "tail_capture_spec": {"frame_selection": "last_complete_frame", "format": "png",
                                  "naming": "{segment_id}_tail.png"},
            "technical_warnings": [],
        }
        payload.update(overrides)
        return {"schema_version": "1.0", "status": "COMPLETE", "failed_stage": None, "agent_id": None,
                "failure_kind": None, "errors": [], "warnings": [], "last_valid_artifacts": {},
                "result": payload}

    def codes(self, artifact):
        return {item["code"] for item in
                validator.validate_result(artifact, self.packages(), None, self.shot())}

    def test_complete_result_is_accepted(self):
        self.assertEqual(validator.validate_result(self.result(), self.packages(), None, self.shot()), [])

    def test_missing_media_is_rejected(self):
        artifact = self.result()
        artifact["result"]["resolved_media"] = artifact["result"]["resolved_media"][:1]
        self.assertIn("result_media_missing", self.codes(artifact))

    def test_resolved_media_without_location_is_rejected(self):
        artifact = self.result()
        artifact["result"]["resolved_media"][0]["location"] = None
        self.assertIn("result_media_location", self.codes(artifact))

    def test_package_drift_is_rejected(self):
        artifact = self.result()
        artifact["result"]["packages"] = [{"segment_id": "SEG999"}]
        self.assertIn("result_package_drift", self.codes(artifact))

    def test_duration_drift_is_rejected(self):
        artifact = self.result()
        artifact["result"]["total_duration"] = 12
        self.assertIn("result_duration_drift", self.codes(artifact))

    def test_aspect_ratio_and_style_must_survive(self):
        artifact = self.result()
        artifact["result"]["aspect_ratio"] = "9:16"
        artifact["result"]["visual_style"] = {}
        codes = self.codes(artifact)
        self.assertIn("result_aspect_ratio_drift", codes)
        self.assertIn("result_visual_style_drift", codes)

    def test_execution_order_must_match_packages(self):
        artifact = self.result()
        artifact["result"]["execution_order"] = [{"order": 1, "segment_id": "SEG002", "depends_on": None}]
        self.assertIn("result_execution_order", self.codes(artifact))

    def test_dependency_must_match_runtime_binding(self):
        artifact = self.result()
        artifact["result"]["execution_order"][0]["depends_on"] = "SEG000"
        self.assertIn("result_dependency_drift", self.codes(artifact))

    def test_optional_context_may_be_omitted(self):
        # The orchestrator validates its own draft before it has the other artifacts.
        self.assertEqual(validator.validate_result(self.result()), [])


if __name__ == "__main__":
    unittest.main()
