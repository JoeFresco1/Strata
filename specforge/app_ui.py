from __future__ import annotations

import streamlit as st

from specforge.config import (
    AppConfig,
    build_llama_server_command,
    build_model_profiles,
    ensure_runtime_dirs,
    resolve_default_model_profile,
    resolve_llama_server_executable,
    resolve_model_path,
)
from specforge.db import Database
from specforge.export import export_project
from specforge.generation import GenerationService, IterativeGenerationSummary
from specforge.llm import LLMError, LlamaCppClient
from specforge.models import Node, Project
from specforge.server_manager import LlamaServerManager


def _bootstrap() -> tuple[AppConfig, Database, LlamaCppClient, GenerationService]:
    config = AppConfig()
    ensure_runtime_dirs(config)
    db = Database(config.db_path)
    llm_client = LlamaCppClient(config)
    server_manager = LlamaServerManager(config)
    return config, db, llm_client, GenerationService(db, llm_client, server_manager)


def _project_label(project: Project) -> str:
    return f"{project.name} | {project.created_at.strftime('%Y-%m-%d %H:%M')}"


def _render_sidebar(config: AppConfig, db: Database, llm_client: LlamaCppClient) -> str | None:
    st.sidebar.title("SpecForge")
    ok, message = llm_client.healthcheck()
    if ok:
        st.sidebar.success(f"LLM server: {message}")
    else:
        st.sidebar.warning(message)
    model_path = resolve_model_path(config)
    server_exe = resolve_llama_server_executable(config)
    st.sidebar.caption("Detected GGUF")
    st.sidebar.code(str(model_path) if model_path else "No model detected", language="text")
    st.sidebar.caption("Detected llama-server")
    st.sidebar.code(str(server_exe) if server_exe else "No llama-server executable detected", language="text")
    st.sidebar.caption("Suggested llama.cpp command")
    st.sidebar.code(build_llama_server_command(config, model_path), language="powershell")

    projects = db.list_projects()
    if not projects:
        st.sidebar.info("Create your first project to get started.")
        return None

    labels = {_project_label(project): project.id for project in projects}
    selected_label = st.sidebar.selectbox("Projects", list(labels.keys()))
    return labels[selected_label]


def _render_new_project(db: Database) -> str | None:
    st.subheader("New Project")
    with st.form("new_project_form", clear_on_submit=False):
        name = st.text_input("Project name", placeholder="SpecForge demo")
        idea = st.text_area(
            "Product idea",
            height=180,
            placeholder="AI financial audit assistant for families",
        )
        create = st.form_submit_button("Create project")
    if create:
        if not name.strip() or not idea.strip():
            st.error("Project name and product idea are both required.")
            return None
        project = db.create_project(name.strip(), idea.strip())
        st.success("Project created.")
        return project.id
    return None


def _status_options() -> list[str]:
    return ["generated", "kept", "cut", "merged", "prioritized"]


def _render_node_editor(db: Database, node: Node) -> None:
    duplicate = node.json_payload.get("possible_duplicate")
    pillar_assessment = node.json_payload.get("pillar_assessment")
    with st.expander(f"{node.title} | {node.node_type} | {node.status}", expanded=False):
        if duplicate:
            st.warning(
                f"Possible duplicate of '{duplicate['duplicate_title']}' "
                f"(title {duplicate['title_score']} / description {duplicate['description_score']})"
            )
        if pillar_assessment:
            st.caption(
                f"Canonical: {pillar_assessment.get('canonical_title', node.title)} | "
                f"Cluster: {pillar_assessment.get('cluster_id', 'n/a')}"
            )
            st.caption(
                f"Quality {pillar_assessment.get('pillar_quality_score', 'n/a')}/100 | "
                f"Distinctiveness {pillar_assessment.get('distinctiveness_score', 'n/a')}/100 | "
                f"Strategic value {pillar_assessment.get('strategic_value_score', 'n/a')}/100"
            )
            if pillar_assessment.get("too_narrow"):
                st.warning("This item was flagged as potentially too narrow for Layer 1.")
            if pillar_assessment.get("too_implementation_specific"):
                st.warning("This item was flagged as potentially too implementation-specific for Layer 1.")
            if pillar_assessment.get("too_broad_generic"):
                st.warning("This item was flagged as potentially too broad or too vague for Layer 1.")
            if pillar_assessment.get("merge_into"):
                st.info(f"Suggested merge target: {pillar_assessment['merge_into']}")
            if pillar_assessment.get("rename_to"):
                st.info(f"Suggested canonical rename: {pillar_assessment['rename_to']}")
            if pillar_assessment.get("sharpen_to"):
                st.info(f"Suggested sharper title: {pillar_assessment['sharpen_to']}")
            if pillar_assessment.get("rationale"):
                st.caption(pillar_assessment["rationale"])
        new_title = st.text_input("Title", value=node.title, key=f"title_{node.id}")
        new_description = st.text_area(
            "Description",
            value=node.description or "",
            key=f"description_{node.id}",
            height=110,
        )
        new_status = st.selectbox(
            "Status",
            _status_options(),
            index=_status_options().index(node.status),
            key=f"status_{node.id}",
        )
        new_priority = st.number_input(
            "Priority",
            min_value=0,
            max_value=10,
            value=int(node.priority or 0),
            key=f"priority_{node.id}",
        )
        if node.json_payload:
            st.caption("Structured payload")
            st.json(node.json_payload)
        if st.button("Save changes", key=f"save_{node.id}"):
            db.update_node(
                node.id,
                title=new_title.strip(),
                description=new_description.strip(),
                status=new_status,
                priority=int(new_priority),
            )
            st.success(f"Updated {new_title.strip()}.")
            st.rerun()


def _render_generation_controls(
    project: Project,
    db: Database,
    generation_service: GenerationService,
) -> None:
    st.subheader("Generate")
    config = AppConfig()
    model_profiles = build_model_profiles(config)
    default_profile = resolve_default_model_profile(config, model_profiles)
    pillars = db.list_nodes(project.id, parent_id=None, layer=1, node_type="pillar")
    st.caption(
        "Layer 1 now broadens through rotating pillar-discovery lenses, then normalizes each batch back to true pillar-level concepts."
    )
    if model_profiles:
        labels = {profile.display_name: profile for profile in model_profiles}
        default_labels = [default_profile.display_name] if default_profile else []
        selected_model_labels = st.multiselect(
            "Layer 1 model sequence",
            list(labels.keys()),
            default=default_labels,
            help="Models run one after another. Later models challenge the coverage created by earlier ones.",
        )
        selected_model_profiles = [labels[label] for label in selected_model_labels]
    else:
        selected_model_profiles = []
        st.warning("No GGUF model profiles discovered for Layer 1 sequencing.")
    thinking_enabled = st.toggle(
        "Enable model thinking mode",
        value=False,
        help="When enabled, SpecForge restarts llama.cpp with reasoning enabled for the selected Layer 1 models.",
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        max_rounds = st.number_input("Layer 1 max rounds", min_value=1, max_value=12, value=6, step=1)
    with col2:
        target_per_round = st.number_input(
            "Layer 1 target per round", min_value=4, max_value=20, value=12, step=1
        )
    with col3:
        min_new_per_round = st.number_input(
            "Stop when new pillars fall below", min_value=1, max_value=10, value=2, step=1
        )

    if st.button("Broaden Layer 1 Until Exhausted", use_container_width=True):
        if not selected_model_profiles:
            st.error("Select at least one Layer 1 model before starting broadening.")
            return
        try:
            summary = generation_service.generate_pillars_until_exhausted(
                project.id,
                model_profiles=selected_model_profiles,
                thinking_enabled=thinking_enabled,
                max_rounds=int(max_rounds),
                target_per_round=int(target_per_round),
                min_new_items_per_round=int(min_new_per_round),
                stale_rounds_to_stop=2,
            )
        except LLMError as exc:
            st.error(str(exc))
        else:
            _render_broadening_summary(summary, "pillars")
            st.rerun()

    kept_pillars = [node for node in pillars if node.status in {"kept", "prioritized"}]
    pillar_choices = {f"{node.title} ({node.status})": node.id for node in kept_pillars}
    st.divider()
    st.caption("Layer 2 can also broaden until saturation for each approved pillar you choose.")
    selected_pillars = st.multiselect("Expand selected pillars into Layer 2", list(pillar_choices.keys()))
    layer2_thinking_enabled = st.toggle(
        "Enable thinking mode for Layer 2",
        value=False,
        help="Restarts the managed llama.cpp server with reasoning enabled for downward Layer 2 generation.",
    )
    sub_col1, sub_col2, sub_col3 = st.columns(3)
    with sub_col1:
        sub_max_rounds = st.number_input("Layer 2 max rounds", min_value=1, max_value=10, value=5, step=1)
    with sub_col2:
        sub_target_per_round = st.number_input(
            "Layer 2 target per round", min_value=4, max_value=20, value=10, step=1
        )
    with sub_col3:
        sub_min_new = st.number_input("Layer 2 min new per round", min_value=1, max_value=10, value=2, step=1)

    if st.button("Broaden Layer 2 Until Saturated", use_container_width=True, disabled=not selected_pillars):
        try:
            summaries = []
            for label in selected_pillars:
                summaries.append(
                    (
                        label,
                        generation_service.generate_subfeatures_until_exhausted(
                            project.id,
                            pillar_choices[label],
                            thinking_enabled=layer2_thinking_enabled,
                            max_rounds=int(sub_max_rounds),
                            target_per_round=int(sub_target_per_round),
                            min_new_items_per_round=int(sub_min_new),
                            stale_rounds_to_stop=2,
                        ),
                    )
                )
        except LLMError as exc:
            st.error(str(exc))
        else:
            for label, summary in summaries:
                st.markdown(f"**{label}**")
                _render_broadening_summary(summary, "subfeatures")
            st.rerun()

    subfeatures = db.list_nodes(project.id, parent_id="__any__", layer=2, node_type="subfeature")
    kept_subfeatures = [node for node in subfeatures if node.status in {"kept", "prioritized"}]
    subfeature_choices = {f"{node.title} ({node.status})": node.id for node in kept_subfeatures}
    layer3_thinking_enabled = st.toggle(
        "Enable thinking mode for Layer 3",
        value=False,
        help="Restarts the managed llama.cpp server with reasoning enabled for implementation spec generation.",
    )
    selected_subfeatures = st.multiselect(
        "Expand selected subfeatures into Layer 3 specs", list(subfeature_choices.keys())
    )
    if st.button("Generate Layer 3 Specs", use_container_width=True, disabled=not selected_subfeatures):
        try:
            created = generation_service.generate_specs(
                project.id,
                [subfeature_choices[label] for label in selected_subfeatures],
                thinking_enabled=layer3_thinking_enabled,
            )
        except LLMError as exc:
            st.error(str(exc))
        else:
            st.success(f"Generated {len(created)} spec nodes.")
            st.rerun()


def _render_broadening_summary(summary: IterativeGenerationSummary, item_label: str) -> None:
    created_count = len(summary.created_nodes)
    round_counts = ", ".join(str(count) for count in summary.per_round_new_counts) or "0"
    st.success(
        f"Broadening finished after {summary.total_rounds} rounds. "
        f"Added {created_count} new {item_label} and stopped because: {summary.stop_reason}."
    )
    st.info(
        f"Round-by-round new {item_label}: {round_counts}. "
        f"Duplicate/repeated candidates skipped: {summary.duplicate_candidates}. "
        f"Filtered candidates skipped: {summary.filtered_candidates}."
    )
    if summary.per_round_new_family_counts:
        family_counts = ", ".join(str(count) for count in summary.per_round_new_family_counts)
        st.caption(f"Round-by-round new pillar families: {family_counts}")
    if summary.unique_family_count:
        st.caption(f"Unique pillar families captured: {summary.unique_family_count}")
    if summary.final_novelty_score is not None:
        st.caption(f"Final novelty score: {summary.final_novelty_score}/100")
    if summary.models_used:
        st.caption(f"Models used: {', '.join(summary.models_used)}")
    st.caption(f"Thinking mode: {'on' if summary.thinking_enabled else 'off'}")
    if summary.lenses_used:
        st.caption(f"Lenses used: {', '.join(summary.lenses_used)}")
    if summary.final_coverage_summary:
        st.caption(summary.final_coverage_summary)
    if summary.round_summaries:
        with st.expander("Round Details", expanded=False):
            for line in summary.round_summaries:
                st.write(f"- {line}")


def _render_feature_tree(project: Project, db: Database) -> None:
    st.subheader("Feature Tree")
    nodes = db.list_all_nodes(project.id)
    if not nodes:
        st.info("No generated nodes yet.")
        return
    pillars = [node for node in nodes if node.layer == 1]
    for pillar in pillars:
        st.markdown(f"### {pillar.title}")
        st.caption(f"{pillar.status} | priority={pillar.priority}")
        assessment = pillar.json_payload.get("pillar_assessment", {})
        if assessment:
            st.caption(
                f"canonical={assessment.get('canonical_title', pillar.title)} | "
                f"quality={assessment.get('pillar_quality_score', 'n/a')}"
            )
        if pillar.description:
            st.write(pillar.description)
        subfeatures = [node for node in nodes if node.parent_id == pillar.id and node.layer == 2]
        for subfeature in subfeatures:
            st.markdown(f"- **{subfeature.title}** ({subfeature.status})")
            if subfeature.description:
                st.write(f"  - {subfeature.description}")
            specs = [node for node in nodes if node.parent_id == subfeature.id and node.layer == 3]
            for spec in specs:
                st.write(f"  - Spec: {spec.title} ({spec.status})")


def _render_review(project: Project, db: Database) -> None:
    st.subheader("Node Review")
    nodes = db.list_all_nodes(project.id)
    if not nodes:
        st.info("Generate something first, then review it here.")
        return
    layer_filter = st.selectbox("Layer", ["All", "1", "2", "3"], index=0)
    type_filter = st.selectbox("Type", ["All", "pillar", "subfeature", "spec"], index=0)
    filtered = nodes
    if layer_filter != "All":
        filtered = [node for node in filtered if node.layer == int(layer_filter)]
    if type_filter != "All":
        filtered = [node for node in filtered if node.node_type == type_filter]
    for node in filtered:
        _render_node_editor(db, node)


def _render_spec_viewer(project: Project, db: Database) -> None:
    st.subheader("Spec Viewer")
    specs = db.list_nodes(project.id, parent_id="__any__", layer=3, node_type="spec")
    if not specs:
        st.info("No specs generated yet.")
        return
    spec_labels = {spec.title: spec.id for spec in specs}
    selected = st.selectbox("Spec", list(spec_labels.keys()))
    spec = db.get_node(spec_labels[selected])
    st.markdown(f"### {spec.title}")
    st.write(spec.description or "")
    st.json(spec.json_payload)


def _render_export(project: Project, db: Database, config: AppConfig) -> None:
    st.subheader("Export")
    nodes = db.list_all_nodes(project.id)
    if not nodes:
        st.info("Nothing to export yet.")
        return
    memories = db.list_project_memory(project.id)
    quarantine_items: list[dict[str, object]] = []
    if memories:
        with st.expander("Generation Memory", expanded=False):
            for memory in memories:
                st.markdown(f"**{memory.scope}** `{memory.memory_type}`")
                if memory.scope_id:
                    st.caption(memory.scope_id)
                st.json(memory.content)
                if memory.scope == "layer1" and memory.memory_type == "quarantine":
                    quarantine_items = [item for item in memory.content.get("items", []) if isinstance(item, dict)]
    if quarantine_items:
        with st.expander("Layer 1 Quarantine", expanded=False):
            for item in quarantine_items:
                st.markdown(f"**{item.get('title', 'Untitled')}**")
                st.caption(
                    f"reason={item.get('reason', 'unknown')} | model={item.get('source_model', 'unknown')} | lens={item.get('source_lens', 'unknown')}"
                )
                if item.get("description"):
                    st.write(str(item["description"]))
                assessment = item.get("assessment")
                if isinstance(assessment, dict) and assessment:
                    st.json(assessment)
    if st.button("Export Markdown + JSON", use_container_width=True):
        markdown_path, json_path = export_project(project, nodes, config.exports_dir)
        st.success("Export complete.")
        st.code(str(markdown_path), language="text")
        st.code(str(json_path), language="text")
    latest_markdown = config.exports_dir / f"{''.join(ch.lower() if ch.isalnum() else '-' for ch in project.name).strip('-') or project.id}.md"
    latest_json = latest_markdown.with_suffix(".json")
    if latest_markdown.exists():
        st.download_button(
            "Download Markdown",
            latest_markdown.read_text(encoding="utf-8"),
            file_name=latest_markdown.name,
            mime="text/markdown",
        )
    if latest_json.exists():
        st.download_button(
            "Download JSON",
            latest_json.read_text(encoding="utf-8"),
            file_name=latest_json.name,
            mime="application/json",
        )


def run_app() -> None:
    st.set_page_config(page_title="SpecForge", layout="wide")
    st.title("SpecForge")
    st.caption("A local recursive feature decomposition engine with human-in-the-loop pruning.")

    config, db, llm_client, generation_service = _bootstrap()
    selected_project_id = _render_sidebar(config, db, llm_client)

    new_project_id = _render_new_project(db)
    active_project_id = new_project_id or selected_project_id
    if active_project_id is None:
        return

    project = db.get_project(active_project_id)
    st.write(project.idea)

    tabs = st.tabs(
        [
            "1. Generate",
            "2. Feature Tree",
            "3. Node Review",
            "4. Spec Viewer",
            "5. Export",
        ]
    )
    with tabs[0]:
        _render_generation_controls(project, db, generation_service)
    with tabs[1]:
        _render_feature_tree(project, db)
    with tabs[2]:
        _render_review(project, db)
    with tabs[3]:
        _render_spec_viewer(project, db)
    with tabs[4]:
        _render_export(project, db, config)
