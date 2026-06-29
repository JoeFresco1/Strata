from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from strata.config import AppConfig, ModelProfile, build_model_profiles, resolve_default_model_profile, resolve_reasoning_settings
from strata.api import _valid_layer2_status, create_app
from strata.assistant_index import AssistantIndexService
from strata.assistant_service import AssistantService
from strata.api_models import Layer2FeatureCreateRequest, Layer2FeatureEvidenceRequest
from strata.db import Database
from strata.embeddings import EmbeddingService
from strata.export import export_layer2_markdown, export_layer3_manifest
from strata.generation import LAYER2_EXHAUSTION_FAMILIES, LAYER2_LENSES, LAYER2_SURVEY_BUILDER_FAMILIES, GenerationService
from strata.llm import LLMError, LlamaCppClient
from strata.layer2_research import Layer2CompetitorSeed, Layer2ResearchMixin
from strata.layer3_service import validate_product_level_content
from strata.models import (
    CapabilityDesignPayload,
    CapabilityDesignResponse,
    CapabilityPressureTest,
    CapabilityPressureTestResponse,
    Layer2Candidate,
    Layer2CandidateResponse,
    Layer2CoverageAssessmentResponse,
    Layer2CoverageFamilyAssessment,
    Node,
    PillarAssessment,
    ProjectMemory,
    SimilarityMatch,
)
from strata.project_settings import default_project_model_settings, normalize_model_settings
from strata.provider_onboarding import ProviderValidator, default_provider_readiness
from strata.prompts import (
    build_pillar_prompt,
    build_pillar_research_assessment_prompt,
    build_system_prompt,
    load_prompt_catalog,
    render_prompt,
)
from strata.brief import BriefService
from strata.research import ResearchService
from strata.research import ExtractedPage
from requests.exceptions import SSLError


class ProjectSettingsTests(unittest.TestCase):
    def test_normalize_model_settings_filters_invalid_profiles_and_assignments(self) -> None:
        config = AppConfig()
        normalized = normalize_model_settings(
            {
                "llm_profiles": [
                    {"id": "alpha", "label": "Alpha", "base_url": "http://localhost:8080/", "model_name": "alpha-model"},
                    {"id": "alpha", "label": "Duplicate", "base_url": "http://localhost:9999", "model_name": "ignored"},
                    {"id": "missing-model", "label": "Missing Model", "base_url": "http://localhost:8081"},
                ],
                "embedding_profiles": [
                    {"id": "embed-a", "label": "Embed A", "model_name": "embed-model"},
                    {"id": "embed-a", "label": "Duplicate", "model_name": "ignored"},
                    {"id": "embed-bad", "label": "Broken", "model_name": ""},
                ],
                "assignments": {
                    "layer0_plan": "alpha",
                    "layer1_generation": ["alpha", "missing", ""],
                    "research_embeddings": "embed-a",
                    "layer0_research": "missing",
                },
            },
            config,
        )

        self.assertEqual(len(normalized["llm_profiles"]), 1)
        self.assertEqual(normalized["llm_profiles"][0]["base_url"], "http://localhost:8080")
        self.assertEqual(len(normalized["embedding_profiles"]), 1)
        self.assertEqual(normalized["execution_intent"], "local_first")
        self.assertEqual(normalized["assignments"]["layer0_plan"], "alpha")
        self.assertEqual(normalized["assignments"]["layer1_generation"], ["alpha"])
        self.assertEqual(normalized["assignments"]["research_embeddings"], "embed-a")
        self.assertEqual(normalized["assignments"]["layer0_research"], "default-chat")

    def test_normalize_model_settings_keeps_blended_intent_and_concurrency(self) -> None:
        normalized = normalize_model_settings(
            {
                "execution_intent": "blended",
                "routing_policy": {"assistant": "api", "generation": "local"},
                "concurrency_policy": {"managed_local_parallelism": 1, "remote_parallelism": 6},
            },
            AppConfig(),
        )

        self.assertEqual(normalized["execution_intent"], "blended")
        self.assertEqual(normalized["routing_policy"]["assistant"], "api")
        self.assertEqual(normalized["routing_policy"]["generation"], "local")
        self.assertEqual(normalized["concurrency_policy"]["remote_parallelism"], 6)


class EmbeddingServiceTests(unittest.TestCase):
    def test_set_model_name_updates_runtime_state(self) -> None:
        service = EmbeddingService(AppConfig())
        service._model = object()  # type: ignore[assignment]
        service.set_model_name("custom/model")

        self.assertEqual(service.model_name, "custom/model")
        self.assertIsNone(service._model)


class LLMClientTests(unittest.TestCase):
    @patch("strata.llm.requests.post")
    def test_generate_json_records_provider_usage(self, mock_post: MagicMock) -> None:
        store = MagicMock()
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "model": "remote-model",
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_post.return_value = response
        client = LlamaCppClient(AppConfig(), telemetry_store=store)

        result = client.generate_json(
            system_prompt="system",
            user_prompt="user",
            base_url="https://models.example.com",
            telemetry={
                "project_id": "project-1",
                "layer": "layer1",
                "workflow": "pillar_generation",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
            },
        )

        self.assertTrue(result.parsed_json["ok"])
        recorded = store.record_model_call.call_args.args[0]
        self.assertEqual(recorded["provider_kind"], "remote")
        self.assertEqual(recorded["total_tokens"], 15)
        self.assertEqual(recorded["estimated_cost_usd"], 0.00002)
        self.assertTrue(recorded["prompt_version"])

    def test_setters_update_runtime_endpoint_and_model(self) -> None:
        client = LlamaCppClient(AppConfig())
        client.set_base_url("http://localhost:9000/")
        client.set_model_name("custom-chat-model")

        self.assertEqual(client.base_url, "http://localhost:9000")
        self.assertEqual(client.model_name, "custom-chat-model")

    def test_strip_reasoning_wrappers_extracts_json_after_prefix(self) -> None:
        cleaned = LlamaCppClient._strip_reasoning_wrappers('thought\n{"pillars":[{"title":"A"}]}')

        self.assertEqual(cleaned, '{"pillars":[{"title":"A"}]}')

    def test_strip_reasoning_wrappers_handles_llama_channel_markers(self) -> None:
        self.assertEqual(
            LlamaCppClient._strip_reasoning_wrappers("<|channel|>thought\n<channel|>GGUF_OK"),
            "GGUF_OK",
        )
        self.assertEqual(
            LlamaCppClient._strip_reasoning_wrappers("<|channel>thought\n<channel|>GGUF_OK"),
            "GGUF_OK",
        )

    def test_strip_reasoning_wrappers_handles_code_fences(self) -> None:
        cleaned = LlamaCppClient._strip_reasoning_wrappers('```json\n{"ok": true}\n```')

        self.assertEqual(cleaned, '{"ok": true}')


class ProviderValidatorTests(unittest.TestCase):
    def test_invalid_url_is_rejected(self) -> None:
        validator = ProviderValidator()

        with self.assertRaisesRegex(ValueError, "full http:// or https:// URL"):
            validator.validate({
                "llama_base_url": "localhost:8080",
                "model_name": "local-model",
                "effective_bearer_token": "",
                "runtime_preset": "llama_cpp",
                "max_output_tokens": 1800,
            })

    @patch("strata.provider_onboarding.requests.get")
    def test_missing_model_is_reported(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(ok=True, json=MagicMock(return_value={"data": [{"id": "other-model"}]}))
        validator = ProviderValidator()

        with self.assertRaisesRegex(ValueError, "was not returned by `/v1/models`"):
            validator.validate({
                "llama_base_url": "http://127.0.0.1:8080",
                "model_name": "local-model",
                "effective_bearer_token": "",
                "runtime_preset": "llama_cpp",
                "max_output_tokens": 1800,
            })

    @patch("strata.provider_onboarding.requests.post")
    @patch("strata.provider_onboarding.requests.get")
    def test_successful_validation_marks_provider_ready(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = MagicMock(ok=True, json=MagicMock(return_value={"data": [{"id": "local-model"}]}))
        mock_post.return_value = MagicMock(ok=True, status_code=200, json=MagicMock(return_value={"choices": [{"message": {"content": "OK"}}]}))
        validator = ProviderValidator()

        result = validator.validate({
            "llama_base_url": "http://127.0.0.1:8080",
            "model_name": "local-model",
            "effective_bearer_token": "",
            "runtime_preset": "llama_cpp",
            "max_output_tokens": 1800,
        })

        self.assertTrue(result.readiness["ready"])
        self.assertTrue(result.readiness["capability_ok"])
        self.assertEqual(result.readiness["preset"], "llama_cpp")


class BriefServiceTests(unittest.TestCase):
    def test_plan_turn_updates_same_canonical_brief(self) -> None:
        class StubClient:
            def generate_json(self, **_: object):
                class Response:
                    parsed_json = {"updates": {"known_competitors": ["Acme"], "goals": ["Faster review"]}}
                return Response()

            def generate_text(self, **_: object) -> str:
                return "Captured. What constraints matter?"

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            db.set_app_setting("provider_readiness", json.dumps({"ready": True, "message": "Ready for tests."}))
            service = BriefService(db, StubClient())  # type: ignore[arg-type]

            reply, brief, guidance = service.append_plan_turn(project.id, "Competitor is Acme.")

            self.assertIn("What became clearer", reply)
            self.assertEqual(brief.known_competitors, ["Acme"])
            self.assertEqual(brief.goals, ["Faster review"])
            self.assertIn("target users", guidance["assistant_message"])
            self.assertEqual(len(db.list_brief_conversation(project.id)), 2)

    def test_plan_turn_request_id_is_idempotent(self) -> None:
        class StubClient:
            calls = 0

            def generate_json(self, **_: object):
                self.calls += 1

                class Response:
                    parsed_json = {"updates": {"goals": ["Faster review"]}}
                return Response()

            def generate_text(self, **_: object) -> str:
                self.calls += 1
                return "Captured."

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            db.set_app_setting("provider_readiness", json.dumps({"ready": True, "message": "Ready for tests."}))
            client = StubClient()
            service = BriefService(db, client)  # type: ignore[arg-type]

            first = service.append_plan_turn(project.id, "Make review faster.", "request-1")
            second = service.append_plan_turn(project.id, "Make review faster.", "request-1")

            self.assertEqual(first[0], second[0])
            self.assertEqual(client.calls, 2)
            self.assertEqual(len(db.list_brief_conversation(project.id)), 2)


