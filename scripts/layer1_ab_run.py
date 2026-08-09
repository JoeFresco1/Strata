from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from strata.config import AppConfig
from strata.db import Database
from strata.generation import GenerationService
from strata.llm import LlamaCppClient
from strata.migrations import apply_migrations


DISCOVERY = {
    "archetypes": [],
    "lenses": [
        {
            "id": "lens-operating-model",
            "title": "Organizational Operating Model",
            "description": "Explore how the platform represents organizational systems, outcomes, and interventions.",
            "why_it_matters": "The product must model the organization rather than collapse into a survey builder.",
            "questions": ["What top-level systems must the product help leaders understand and change?"],
            "expected_product_territory": ["organizational model", "decision support", "interventions"],
            "relevance_score": 1.0,
            "recommendation": "required",
            "downstream_state": "required",
        },
        {
            "id": "lens-authority",
            "title": "Actors, Authority, and Decision Rights",
            "description": "Explore distinct experiences for respondents, managers, analysts, program owners, and administrators.",
            "why_it_matters": "Different actors have different authority, evidence, and action responsibilities.",
            "questions": ["Who can configure, approve, interpret, act, audit, and challenge?"],
            "expected_product_territory": ["role-specific workspaces", "delegated authority", "decision workflows"],
            "relevance_score": 1.0,
            "recommendation": "required",
            "downstream_state": "required",
        },
        {
            "id": "lens-lifecycle",
            "title": "Lifecycle and Action Capacity",
            "description": "Explore the full loop from configuration and measurement through interpretation, intervention, monitoring, and renewal.",
            "why_it_matters": "Insight without a bounded action loop creates dashboards rather than an operating product.",
            "questions": ["How does evidence become an approved action and how is impact monitored?"],
            "expected_product_territory": ["program lifecycle", "intervention planning", "impact monitoring"],
            "relevance_score": 1.0,
            "recommendation": "required",
            "downstream_state": "required",
        },
        {
            "id": "lens-privacy",
            "title": "Privacy, Trust, and Statistical Safeguards",
            "description": "Explore confidentiality, minimum reporting groups, consent, explainability, and misuse prevention.",
            "why_it_matters": "Workforce data can harm people when identity, inference, or small groups are mishandled.",
            "questions": ["What safeguards constrain collection, inference, reporting, and action?"],
            "expected_product_territory": ["privacy controls", "statistical safeguards", "trust and transparency"],
            "relevance_score": 1.0,
            "recommendation": "required",
            "downstream_state": "required",
        },
        {
            "id": "lens-enterprise",
            "title": "Enterprise Administration and Operations",
            "description": "Explore tenant setup, delegated administration, entitlements, support, audit, and operational health.",
            "why_it_matters": "The core intelligence loop must remain operable across real enterprise customers.",
            "questions": ["What platform territory is needed to deploy and govern this at scale?"],
            "expected_product_territory": ["tenant operations", "entitlements", "support operations", "audit"],
            "relevance_score": 0.95,
            "recommendation": "required",
            "downstream_state": "required",
        },
        {
            "id": "lens-data",
            "title": "Data, Integrations, and Evidence Quality",
            "description": "Explore data intake, HRIS and workflow integrations, longitudinal evidence, and data quality.",
            "why_it_matters": "Recommendations are only as credible as their evidence and operational connections.",
            "questions": ["How are heterogeneous signals connected, qualified, and kept current?"],
            "expected_product_territory": ["connectors", "evidence graph", "data quality", "longitudinal analysis"],
            "relevance_score": 0.95,
            "recommendation": "required",
            "downstream_state": "required",
        },
        {
            "id": "lens-market",
            "title": "Category Differentiation",
            "description": "Explore defensible territory beyond engagement surveys, generic dashboards, and consulting reports.",
            "why_it_matters": "The architecture should preserve the product thesis rather than imitate incumbent packaging.",
            "questions": ["Which product systems make this an intelligence and action platform?"],
            "expected_product_territory": ["simulation", "decision science", "closed-loop action"],
            "relevance_score": 0.8,
            "recommendation": "recommended",
        },
    ],
    "actors": [
        {"id": "actor-employee", "title": "Employee or respondent", "description": "Contributes protected evidence."},
        {"id": "actor-manager", "title": "Manager", "description": "Interprets local evidence and owns bounded actions."},
        {"id": "actor-analyst", "title": "People analyst", "description": "Validates evidence and diagnoses patterns."},
        {"id": "actor-owner", "title": "Program owner", "description": "Designs programs and governs interventions."},
        {"id": "actor-admin", "title": "Tenant administrator", "description": "Configures access, integrations, and policy."},
        {"id": "actor-executive", "title": "Executive decision maker", "description": "Allocates resources and reviews outcomes."},
    ],
    "lifecycle_stages": [],
    "enterprise_obligations": [
        {"id": "obligation-access", "title": "Roles, permissions, and delegated administration"},
        {"id": "obligation-audit", "title": "Audit, retention, deletion, and evidence export"},
        {"id": "obligation-ops", "title": "Tenant health, support tooling, and incident response"},
    ],
    "domains": [
        {"id": "domain-model", "title": "Organizational system modeling"},
        {"id": "domain-measure", "title": "Adaptive evidence collection"},
        {"id": "domain-intelligence", "title": "Diagnosis, simulation, and decision support"},
        {"id": "domain-action", "title": "Intervention design and action governance"},
        {"id": "domain-learning", "title": "Outcome monitoring and organizational learning"},
        {"id": "domain-platform", "title": "Enterprise platform operations"},
    ],
    "cross_domain_opportunities": [],
    "coverage_risks": [
        {
            "id": "risk-dashboard",
            "title": "Premature convergence on surveys and dashboards",
            "severity": "critical",
            "recommended_layer1_attention": "Preserve modeling, decision, action, and learning territory.",
        }
    ],
    "open_questions": [],
    "summary": {"fixture": "organizational-intelligence-v1"},
}


def seed_database(database_path: Path) -> tuple[Database, str]:
    db = Database(database_path)
    apply_migrations(db)
    project = db.create_project(
        "Layer 1 A/B Organizational Intelligence",
        "An organizational intelligence and action platform.",
    )
    db.upsert_project_brief(
        project_id=project.id,
        product_idea=(
            "An enterprise organizational intelligence platform that helps leaders understand "
            "organizational systems, collect proportionate evidence, simulate interventions, "
            "govern action, and learn from outcomes without becoming a generic survey builder."
        ),
        problem=(
            "Organizations collect fragmented workforce data but converge prematurely on dashboards "
            "and generic recommendations that lack causal discipline, privacy safeguards, and action capacity."
        ),
        target_users="Employees, managers, people analysts, program owners, tenant administrators, and executives.",
        known_competitors=["Qualtrics", "Culture Amp", "Workday Peakon"],
        constraints="Local-first; privacy-preserving; explainable; human approval before consequential action.",
        goals=[
            "Exhaust the design space before selecting a pillar architecture.",
            "Connect evidence to governed intervention and measurable learning.",
        ],
        preferred_directions=["breadth before depth", "human authority", "closed-loop action"],
        rejected_directions=["generic survey builder", "opaque autonomous decisions"],
        status="published",
    )
    head = db.ensure_brief_revision_head(project.id)
    revision = db.create_discovery_revision(
        project_id=project.id,
        source_brief_revision_id=str(head["current_published_revision_id"]),
        competitor_research_mode="no_competitor_research",
        payload=DISCOVERY,
        command_id="layer1-ab-fixture",
    )
    db.transition_discovery_revision(
        revision_id=revision.id,
        target_state="approved",
        command_id="layer1-ab-approve",
        actor="ab-harness",
        origin="evaluation",
    )
    db.transition_discovery_revision(
        revision_id=revision.id,
        target_state="published",
        command_id="layer1-ab-publish",
        actor="ab-harness",
        origin="evaluation",
    )
    return db, project.id


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one isolated Layer 1 A/B arm.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--target-per-round", type=int, default=6)
    args = parser.parse_args()
    if args.database.exists() or args.output.exists():
        raise SystemExit("Refusing to overwrite an existing A/B database or result file.")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    db, project_id = seed_database(args.database)
    config = AppConfig(
        database_backend="sqlite",
        db_path=args.database,
        llama_base_url="http://127.0.0.1:8080",
        llama_timeout_seconds=600,
        model_name="gemma-4-12b-it-UD-Q6_K_XL",
        embeddings_enabled=False,
        max_output_tokens=2200,
    )
    service = GenerationService(db, LlamaCppClient(config, telemetry_store=db))
    started = time.perf_counter()
    summary = service.generate_pillars_until_exhausted(
        project_id,
        max_rounds=args.max_rounds,
        target_per_round=args.target_per_round,
        min_new_items_per_round=1,
        stale_rounds_to_stop=2,
    )
    elapsed = time.perf_counter() - started
    pillars = db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
    dispositions: list[dict[str, object]] = []
    run_row = None
    if "layer1_expansion_runs" in db._table_names():
        run_row = dict(db._fetchone(
            f"SELECT * FROM layer1_expansion_runs WHERE project_id = {db.param} ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ) or {})
        if run_row:
            dispositions = db.list_layer1_candidate_dispositions(str(run_row["id"]))
    payload = {
        "label": args.label,
        "project_id": project_id,
        "elapsed_seconds": round(elapsed, 3),
        "summary": {
            "total_rounds": summary.total_rounds,
            "created_count": len(summary.created_nodes),
            "duplicate_candidates": summary.duplicate_candidates,
            "filtered_candidates": summary.filtered_candidates,
            "unique_family_count": summary.unique_family_count,
            "stop_reason": summary.stop_reason,
            "per_round_new_counts": summary.per_round_new_counts,
            "per_round_new_family_counts": summary.per_round_new_family_counts,
            "lenses_used": summary.lenses_used,
            "round_summaries": summary.round_summaries,
        },
        "pillars": [
            {"id": pillar.id, "title": pillar.title, "description": pillar.description}
            for pillar in pillars
        ],
        "expansion_run": run_row,
        "disposition_counts": dict(Counter(str(item["disposition"]) for item in dispositions)),
        "undispositioned_candidates": sum(
            1 for item in dispositions if item["disposition"] == "generated"
        ),
        "candidate_dispositions": dispositions,
    }
    args.output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "label": args.label,
        "created_count": len(summary.created_nodes),
        "stop_reason": summary.stop_reason,
        "elapsed_seconds": round(elapsed, 3),
        "output": str(args.output),
    }))


if __name__ == "__main__":
    main()
