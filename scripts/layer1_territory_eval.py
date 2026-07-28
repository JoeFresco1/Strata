from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from pathlib import Path
from typing import Any

try:
    from scripts.layer1_ab_run import DISCOVERY
except ModuleNotFoundError:
    from layer1_ab_run import DISCOVERY
from strata.config import AppConfig
from strata.db import Database
from strata.generation import GenerationService
from strata.layer1_territory_policy import DivergencePolicy, ExplorationBudget
from strata.layer1_territory_models import ClosedTerritoryScope, PolicyHumanState
from strata.llm import LLMError, LlamaCppClient
from strata.migrations import apply_migrations
from strata.telemetry import model_call_context


EVALUATION_LENSES = (
    "Actors, Authority, and Decision Rights",
    "Enterprise Administration and Operations",
    "Data, Integrations, and Evidence Quality",
)
GENERIC_ATTRACTORS = {
    "evidence": ("evidence", "data acquisition", "collection"),
    "modeling": ("model", "digital twin", "system map"),
    "diagnosis": ("simulation", "diagnosis", "analytics"),
    "governance": ("governance", "intervention", "action"),
    "learning": ("learning", "feedback", "impact"),
}
REJECTED_DESTINATIONS = {
    "duplicate",
    "out_of_scope",
    "rejected_quality",
    "rejected_generic_repetition",
    "rejected_unsupported",
    "rejected_bizarre",
}


def evaluation_discovery() -> dict[str, Any]:
    """Return the fixed three-lens fixture shared by every arm and model profile."""
    discovery = copy.deepcopy(DISCOVERY)
    discovery["lenses"] = [
        item for item in discovery["lenses"] if item["title"] in EVALUATION_LENSES
    ]
    required_ids = {
        "Actors, Authority, and Decision Rights": [
            "actor-manager",
            "actor-analyst",
            "actor-owner",
            "actor-admin",
            "actor-executive",
        ],
        "Enterprise Administration and Operations": [
            "actor-admin",
            "obligation-access",
            "obligation-audit",
            "obligation-ops",
            "domain-platform",
        ],
        "Data, Integrations, and Evidence Quality": [
            "actor-analyst",
            "actor-admin",
            "domain-measure",
            "obligation-audit",
            "risk-dashboard",
        ],
    }
    for lens in discovery["lenses"]:
        lens["required_discovery_item_ids"] = required_ids[lens["title"]]
    discovery["summary"] = {
        "fixture": "organizational-intelligence-three-lens-v2",
        "lens_titles": list(EVALUATION_LENSES),
    }
    return discovery


def seed_database(database_path: Path) -> tuple[Database, str, str]:
    """Create one isolated exact-lineage evaluation project."""
    db = Database(database_path)
    apply_migrations(db)
    project = db.create_project(
        "Layer 1 Territory Evaluation",
        "An organizational intelligence and action platform.",
    )
    db.upsert_project_brief(
        project_id=project.id,
        product_idea=(
            "An enterprise organizational intelligence platform that helps leaders "
            "understand systems, govern action, and learn from outcomes."
        ),
        problem=(
            "Organizations converge prematurely on dashboards and generic "
            "recommendations without authority, operational, or integration depth."
        ),
        target_users=(
            "Employees, managers, analysts, program owners, administrators, and executives."
        ),
        known_competitors=["Qualtrics", "Culture Amp", "Workday Peakon"],
        constraints="Local-first, privacy-preserving, explainable, and human-controlled.",
        goals=["Exhaust product territory before selecting a pillar architecture."],
        preferred_directions=["breadth before depth", "human authority"],
        rejected_directions=["generic survey builder", "opaque autonomous decisions"],
        status="published",
    )
    head = db.ensure_brief_revision_head(project.id)
    discovery = evaluation_discovery()
    fixture_hash = hashlib.sha256(
        json.dumps(discovery, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    revision = db.create_discovery_revision(
        project_id=project.id,
        source_brief_revision_id=str(head["current_published_revision_id"]),
        competitor_research_mode="no_competitor_research",
        payload=discovery,
        command_id="layer1-territory-eval",
    )
    db.transition_discovery_revision(
        revision_id=revision.id,
        target_state="approved",
        command_id="layer1-territory-eval-approve",
        actor="evaluation-harness",
        origin="evaluation",
    )
    db.transition_discovery_revision(
        revision_id=revision.id,
        target_state="published",
        command_id="layer1-territory-eval-publish",
        actor="evaluation-harness",
        origin="evaluation",
    )
    return db, project.id, fixture_hash


def run_existing(service: GenerationService, project_id: str) -> dict[str, Any]:
    """Run the small sequential pillar-oriented control arm."""
    brief = service._published_product_idea(project_id)
    discovery = evaluation_discovery()
    pillars: list[dict[str, str]] = []
    malformed_calls = 0
    for lens in discovery["lenses"]:
        prompt = f"""
Generate six strong Layer 1 product pillars for this product.

Product:
{brief}

Use this lens positively to improve the pillar list:
{json.dumps(lens, ensure_ascii=False, sort_keys=True)}

Prior pillars from earlier rounds:
{json.dumps(pillars, ensure_ascii=False, sort_keys=True)}

Return a compact, coherent, defensible set. Merge overlap and self-edit weak ideas.
Return JSON:
{{"pillars":[{{"title":"","description":"","why_it_matters":""}}]}}
""".strip()
        try:
            response = service.llm_client.generate_json(
                system_prompt=service._system_prompt(project_id),
                user_prompt=prompt,
                max_tokens=2600,
                temperature=0.4,
                timeout_seconds=900,
                telemetry=model_call_context(
                    project_id=project_id,
                    layer="layer1",
                    workflow="layer1_existing_style_eval",
                    runtime_profile=None,
                    run_id=None,
                    prompt_key="layer1_existing_style_eval",
                    retry_count=0,
                    metadata={"lens_id": lens["id"], "sequential_context": True},
                ),
            )
            items = response.parsed_json.get("pillars")
            if not isinstance(items, list):
                raise LLMError("Existing-style response omitted the pillars list.")
            pillars.extend({
                "title": str(item.get("title") or "Untitled pillar"),
                "description": str(item.get("description") or ""),
                "source_lens": str(lens["title"]),
            } for item in items if isinstance(item, dict))
        except LLMError:
            malformed_calls += 1
    return {
        "status": "completed" if malformed_calls == 0 else "partial",
        "stop_reason": "three_lens_control_complete",
        "created_count": len(pillars),
        "malformed_calls": malformed_calls,
        "pillars": pillars,
    }


def run_divergent(
    service: GenerationService,
    project_id: str,
    *,
    max_output_tokens: int = 10000,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Run independent high-quantity territory calls with contrastive exclusions."""
    run = service.start_layer1_territory_expansion(
        project_id,
        policy=DivergencePolicy(
            target_raw_candidates=15,
            minimum_raw_candidates=15,
            maximum_raw_candidates=15,
            max_attempts_per_lens=1,
            model_call_timeout_seconds=timeout_seconds,
            divergence_max_output_tokens=max_output_tokens,
            enable_adversarial_pass=False,
            architecture_views=("coherent_core", "expansive_differentiation"),
        ),
        budget=ExplorationBudget(
            max_model_calls=3,
            max_elapsed_seconds=9000,
            max_total_candidates=60,
        ),
    )
    for index, (title, examples) in enumerate((
        ("Evidence and data acquisition", ["evidence collection", "data acquisition"]),
        ("Organizational or systems modeling", ["organizational modeling", "system map"]),
        ("Simulation and diagnosis", ["simulation", "diagnostic analytics"]),
        ("Governance and intervention", ["action governance", "intervention planning"]),
        ("Learning and feedback", ["feedback loop", "impact measurement"]),
    )):
        service.db.append_closed_territory_revision(
            project_id=project_id,
            logical_id=f"experiment-control-{index}",
            run_id=run.id,
            title=title,
            description="Known generic attractor closed by the controlled experiment.",
            semantic_examples=examples,
            source_family_ids=[],
            source="experiment_control",
            scope=ClosedTerritoryScope.RUN,
            active=True,
            human_state=PolicyHumanState.APPROVED,
            reason="Contrastive exclusion control.",
            actor="evaluation-harness",
            command_id=f"experiment-control-{index}",
        )
    result = service.run_layer1_territory_expansion(run.id)
    return {
        "status": result.status.value,
        "stop_reason": result.incomplete_reasons,
        "run_id": run.id,
        "result": result.model_dump(mode="json"),
    }


def evaluate_result(
    db: Database,
    project_id: str,
    arm: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Calculate the same breadth, adherence, usefulness, and reliability rubric."""
    if arm == "existing":
        pillars = result["pillars"]
        texts = [f"{item['title']} {item['description']}".casefold() for item in pillars]
        families = {_semantic_family(text) for text in texts}
        lens_hits = sum(
            1
            for item, text in zip(pillars, texts, strict=False)
            if _text_matches_lens(text, str(item["source_lens"]), discovery=evaluation_discovery())
        )
        generic_hits = sum(1 for text in texts if _generic_family(text) is not None)
        discovery = evaluation_discovery()
        useful = sum(
            1
            for item, text in zip(pillars, texts, strict=False)
            if len(text.split()) >= 12
            and (
                _generic_family(text) is None
                or _text_matches_lens(text, str(item["source_lens"]), discovery=discovery)
            )
        )
        return {
            "raw_candidates": len(pillars),
            "unique_semantic_families": len(families),
            "lens_adherence_score": _rate(lens_hits, len(pillars)),
            "generic_repetition_rate": _rate(generic_hits, len(pillars)),
            "actor_coverage": _text_coverage(texts, discovery["actors"]),
            "enterprise_obligation_coverage": _text_coverage(
                texts,
                discovery["enterprise_obligations"],
            ),
            "operational_capability_coverage": sum(
                1 for text in texts if "operat" in text or "admin" in text
            ),
            "candidate_usefulness_rate": _rate(useful, len(pillars)),
            "malformed_output_rate": _telemetry_failure_rate(db, project_id),
        }
    run_id = str(result["run_id"])
    candidates = db.list_layer1_raw_candidates(run_id)
    dispositions = [
        db.get_current_layer1_candidate_disposition(item.id) for item in candidates
    ]
    latest_coverage = [
        assessments[-1]
        for lens in db.list_layer1_lens_work_items(run_id)
        if (assessments := db.list_layer1_lens_coverage(lens.id))
    ]
    families = {
        _semantic_family(f"{item.title} {item.description}".casefold())
        for item in candidates
    }
    useful = sum(
        1
        for item in dispositions
        if item is not None and item.destination.value not in REJECTED_DESTINATIONS
    )
    attempts = db.list_layer1_lens_attempts(run_id)
    malformed = sum(
        1 for item in attempts if item.status.value in {"schema_failed", "failed"}
    )
    return {
        "raw_candidates": len(candidates),
        "unique_semantic_families": len(families),
        "lens_adherence_score": _average(
            [item.lens_adherence_score / 100 for item in latest_coverage]
        ),
        "generic_repetition_rate": _average(
            [item.generic_repetition_rate for item in latest_coverage]
        ),
        "actor_coverage": _linked_discovery_coverage(
            candidates,
            "actors",
            "affected_actor_ids",
        ),
        "enterprise_obligation_coverage": _linked_discovery_coverage(
            candidates,
            "enterprise_obligations",
            "affected_enterprise_obligation_ids",
        ),
        "operational_capability_coverage": sum(
            1
            for item in dispositions
            if item is not None and item.destination.value == "operational_capability"
        ),
        "candidate_usefulness_rate": _rate(useful, len(candidates)),
        "malformed_output_rate": _rate(malformed, len(attempts)),
    }


def _linked_discovery_coverage(
    candidates: list[Any],
    discovery_category: str,
    affected_attribute: str,
) -> int:
    """Count fixture IDs linked as either candidate sources or affected context."""
    expected_ids = {
        str(item["id"])
        for item in evaluation_discovery()[discovery_category]
        if item.get("id")
    }
    linked_ids = {
        item_id
        for candidate in candidates
        for item_id in (
            list(candidate.source_discovery_item_ids)
            + list(getattr(candidate, affected_attribute))
        )
    }
    return len(expected_ids & linked_ids)


def _semantic_family(text: str) -> str:
    """Return a reproducible coarse family without claiming semantic equivalence."""
    generic = _generic_family(text)
    if generic is not None:
        return generic
    tokens = [
        token
        for token in "".join(char if char.isalnum() else " " for char in text).split()
        if len(token) > 4
    ]
    return " ".join(tokens[:3]) or "unclassified"


def _generic_family(text: str) -> str | None:
    """Detect the known organizational-intelligence generic attractor."""
    for family, phrases in GENERIC_ATTRACTORS.items():
        if any(phrase in text for phrase in phrases):
            return f"generic:{family}"
    return None


def _text_coverage(texts: list[str], items: list[dict[str, Any]]) -> int:
    """Count discovery items whose meaningful title tokens appear in output."""
    covered = 0
    for item in items:
        tokens = [
            token.casefold()
            for token in str(item.get("title") or "").split()
            if len(token) > 5
        ]
        if tokens and any(any(token in text for token in tokens) for text in texts):
            covered += 1
    return covered


def _text_matches_lens(
    text: str,
    lens_title: str,
    *,
    discovery: dict[str, Any],
) -> bool:
    """Score control output against the assigned lens's required source items."""
    lens = next(
        (item for item in discovery["lenses"] if item["title"] == lens_title),
        None,
    )
    if lens is None:
        return False
    required_ids = set(lens.get("required_discovery_item_ids", []))
    source_items = [
        item
        for collection in (
            "actors",
            "domains",
            "enterprise_obligations",
            "coverage_risks",
        )
        for item in discovery.get(collection, [])
        if item.get("id") in required_ids
    ]
    terms = {
        token.casefold()
        for item in source_items
        for token in str(item.get("title") or item.get("name") or "").split()
        if len(token) > 4
    }
    return bool(terms and any(term in text for term in terms))


def _telemetry_failure_rate(db: Database, project_id: str) -> float:
    """Calculate malformed or failed calls from durable model telemetry."""
    rows = db._fetchall(
        f"SELECT status, error_type FROM model_call_events WHERE project_id = {db.param}",
        (project_id,),
    )
    failures = sum(
        1
        for row in rows
        if str(row["status"]) == "failed"
        and str(row["error_type"] or "") in {"parse_error", "schema_failed"}
    )
    return _rate(failures, len(rows))


def _rate(numerator: int, denominator: int) -> float:
    """Return a stable zero-to-one rate."""
    return round(numerator / denominator, 4) if denominator else 0.0


def _average(values: list[float]) -> float:
    """Return a stable average for evaluation output."""
    return round(sum(values) / len(values), 4) if values else 0.0


def _model_file_provenance(model_path: Path | None) -> dict[str, Any] | None:
    """Hash an optional local control model so quantization evidence is exact."""
    if model_path is None:
        return None
    if not model_path.is_file():
        raise SystemExit(f"Model path does not exist: {model_path}")
    digest = hashlib.sha256()
    with model_path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return {
        "path": str(model_path.resolve()),
        "size_bytes": model_path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def main() -> None:
    """Run one isolated evaluation arm without overwriting prior evidence."""
    parser = argparse.ArgumentParser(description="Evaluate one Layer 1 generation arm.")
    parser.add_argument("--arm", choices=("existing", "divergent"), required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile-label", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=10000,
        help="Divergent-call output ceiling; keep identical across model controls.",
    )
    parser.add_argument(
        "--rescore-from",
        type=Path,
        help="Recalculate metrics from an existing result without rerunning inference.",
    )
    args = parser.parse_args()
    if args.rescore_from is not None:
        if not args.database.exists() or not args.rescore_from.exists():
            raise SystemExit("Rescoring requires the existing database and result artifact.")
        if args.output.exists():
            raise SystemExit("Refusing to overwrite an existing evaluation artifact.")
        source_payload = json.loads(args.rescore_from.read_text(encoding="utf-8"))
        db = Database(args.database)
        projects = db.list_projects()
        if len(projects) != 1:
            raise SystemExit("Rescoring expects exactly one isolated evaluation project.")
        payload = {
            **source_payload,
            "metrics": evaluate_result(
                db,
                str(projects[0]["id"]),
                args.arm,
                source_payload["result"],
            ),
            "rescored_from": str(args.rescore_from),
            "model_file": _model_file_provenance(args.model_path),
        }
        args.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True, default=str),
            encoding="utf-8",
        )
        print(json.dumps({"arm": args.arm, "metrics": payload["metrics"], "output": str(args.output)}))
        return
    if args.database.exists() or args.output.exists():
        raise SystemExit("Refusing to overwrite an existing evaluation artifact.")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    db, project_id, fixture_hash = seed_database(args.database)
    config = AppConfig(
        database_backend="sqlite",
        db_path=args.database,
        llama_base_url=args.base_url,
        llama_timeout_seconds=args.timeout_seconds,
        model_name=args.model_name,
        embeddings_enabled=False,
        max_output_tokens=7000,
    )
    service = GenerationService(db, LlamaCppClient(config, telemetry_store=db))
    started = time.perf_counter()
    result = (
        run_existing(service, project_id)
        if args.arm == "existing"
        else run_divergent(
            service,
            project_id,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout_seconds,
        )
    )
    elapsed = time.perf_counter() - started
    payload = {
        "arm": args.arm,
        "profile_label": args.profile_label,
        "model_name": args.model_name,
        "model_file": _model_file_provenance(args.model_path),
        "fixture_hash": fixture_hash,
        "lenses": list(EVALUATION_LENSES),
        "elapsed_seconds": round(elapsed, 3),
        "metrics": evaluate_result(db, project_id, args.arm, result),
        "result": result,
    }
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps({
        "arm": args.arm,
        "profile_label": args.profile_label,
        "fixture_hash": fixture_hash,
        "elapsed_seconds": round(elapsed, 3),
        "metrics": payload["metrics"],
        "output": str(args.output),
    }))


if __name__ == "__main__":
    main()
