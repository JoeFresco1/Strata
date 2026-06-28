from __future__ import annotations

from typing import Any

from strata.models import FeatureGranularity, Layer2Candidate, Node, PillarScopeContract


class Layer2PipelineMixin:
    """Raw candidate processing, canonical feature creation, and graph artifact helpers."""

    def _process_layer2_candidate_batch(
        self,
        *,
        project_id: str,
        run_id: str,
        pillar: Node,
        selected_pillars: list[Node],
        runtime_profile: dict[str, Any],
        source_model: str,
        lens_name: str,
        generation_round: int,
        product_idea: str,
        prompt_catalog: dict[str, str],
        scope_contract: PillarScopeContract,
        candidates: list[Layer2Candidate],
        max_new_features: int | None,
        stats: dict[str, Any],
    ) -> list[str]:
        """Persist raw candidates, apply semantic veto, run critics, and create graph features."""
        raw_pairs: list[tuple[Any, Layer2Candidate]] = []
        for candidate in candidates[:max_new_features] if max_new_features is not None else candidates:
            stats["raw_candidate_count"] += 1
            veto = self._layer2_semantic_negative_cache_veto(project_id, candidate)
            if veto and veto["action"] == "auto_reject":
                stats["negative_cache_matches"] += 1
                self.db.insert_layer2_raw_candidate(
                    project_id=project_id,
                    generation_run_id=run_id,
                    source_pillar_id=pillar.id,
                    source_lens=lens_name,
                    source_model=source_model,
                    generation_round=generation_round,
                    raw_text=candidate.model_dump_json(),
                    payload={**candidate.model_dump(mode="json"), "negative_cache_veto": veto},
                    negative_cache_match=True,
                    negative_cache_reason=f"Auto-rejected repeat of '{veto['rejected_name']}' at similarity {veto['similarity']}.",
                )
                continue
            raw = self.db.insert_layer2_raw_candidate(
                project_id=project_id,
                generation_run_id=run_id,
                source_pillar_id=pillar.id,
                source_lens=lens_name,
                source_model=source_model,
                generation_round=generation_round,
                raw_text=candidate.model_dump_json(),
                payload={
                    **candidate.model_dump(mode="json"),
                    "is_potential_negative_cache_repeat": bool(veto),
                    "negative_cache_context": veto or {},
                },
                negative_cache_match=bool(veto),
                negative_cache_reason=(
                    f"Potential repeat of '{veto['rejected_name']}' at similarity {veto['similarity']}."
                    if veto else ""
                ),
            )
            if veto:
                stats["negative_cache_matches"] += 1
            raw_pairs.append((raw, candidate))

        if not raw_pairs:
            return []

        integrity = self._run_layer2_integrity_critic(
            project_id=project_id,
            pillar_id=pillar.id,
            runtime_profile=runtime_profile,
            product_idea=product_idea,
            prompt_catalog=prompt_catalog,
            scope_contract=scope_contract,
            raw_pairs=raw_pairs,
        )
        integrity_by_id = {item.candidate_id: item for item in integrity.assessments}
        created_feature_ids: list[str] = []
        selected_pillar_ids = [item.id for item in selected_pillars]
        for raw, candidate in raw_pairs:
            if max_new_features is not None and len(created_feature_ids) >= max_new_features:
                break
            assessment = integrity_by_id.get(raw.id)
            granularity = assessment.granularity_class if assessment else FeatureGranularity.FEATURE
            ambiguity_score = assessment.ambiguity_score if assessment else 0.0
            drift_flag = bool(
                (assessment and assessment.is_out_of_bounds)
                or granularity in {FeatureGranularity.TOO_BROAD, FeatureGranularity.TOO_LOW_LEVEL}
                or candidate.scope_classification != "in_scope"
            )
            metadata = self._layer2_feature_metadata(
                candidate,
                selected_pillars,
                pillar.id,
                lens_name,
                source_model,
                raw.negative_cache_match,
                raw.negative_cache_reason,
            )
            metadata.update(
                {
                    "raw_candidate_id": raw.id,
                    "granularity_class": granularity.value,
                    "integrity_reason": assessment.reason if assessment else "",
                    "ambiguity_score": ambiguity_score,
                    "ambiguity_flag": ambiguity_score >= 0.55,
                    "scope_drift_flag": drift_flag,
                }
            )
            if granularity == FeatureGranularity.SHARED_CONCERN:
                self._route_layer2_shared_concern(
                    project_id=project_id,
                    name=candidate.canonical_name,
                    concern_type=self._infer_shared_concern_type(candidate),
                    connected_feature_ids=[],
                )
                continue
            status = self._layer2_candidate_status(candidate, raw.negative_cache_match)
            if drift_flag or ambiguity_score >= 0.55:
                status = "needs_review"
            feature = self.db.create_layer2_feature(
                project_id=project_id,
                canonical_name=candidate.canonical_name.strip(),
                description=candidate.description.strip(),
                feature_type=self._safe_layer2_feature_type(candidate.feature_type),
                granularity_class=granularity.value,
                owner_pillar_id=pillar.id,
                candidate_source_ids=[raw.id],
                aliases=candidate.aliases,
                status=status,
                related_pillar_ids=self._valid_related_pillar_ids(candidate.related_pillar_ids, selected_pillar_ids),
                used_by_feature_ids=[],
                depends_on_feature_ids=[],
                quality={**candidate.model_dump(mode="json"), "needs_human_review": status == "needs_review" or candidate.needs_human_review},
                metadata=metadata,
            )
            stats["created_feature_ids"].append(feature.id)
            created_feature_ids.append(feature.id)
            self._store_layer2_affinities(project_id, feature.id, candidate, selected_pillars, pillar.id)
            existing, overlap_score = self._find_layer2_overlap(project_id, candidate, exclude_feature_ids=[feature.id])
            if existing is not None:
                stats["duplicate_recommendations"] += 1
                self._record_layer2_duplicate_recommendation(project_id, feature.id, existing.id, existing.canonical_name, overlap_score)

        if created_feature_ids:
            graph_critic = self._run_layer2_graph_critic(
                project_id=project_id,
                runtime_profile=runtime_profile,
                product_idea=product_idea,
                prompt_catalog=prompt_catalog,
                current_feature_ids=created_feature_ids,
            )
            self._apply_layer2_graph_directives(project_id, graph_critic, stats)
        return created_feature_ids

    def _record_layer2_duplicate_recommendation(
        self,
        project_id: str,
        feature_id: str,
        existing_feature_id: str,
        existing_feature_name: str,
        overlap_score: float,
    ) -> None:
        """Create the review artifacts for a possible Layer 2 duplicate."""
        self.db.insert_layer2_relationship(
            project_id=project_id,
            source_feature_id=feature_id,
            target_feature_id=existing_feature_id,
            relationship_type="duplicate_of",
            strength=overlap_score,
            rationale=f"Generated candidate resembles existing Layer 2 feature '{existing_feature_name}'.",
        )
        self.db.record_layer2_review_action(
            project_id=project_id,
            feature_id=feature_id,
            action_type="merge",
            payload={
                "recommended_target_feature_id": existing_feature_id,
                "recommended_target_name": existing_feature_name,
                "reason": "Possible duplicate found during Layer 2 graph normalization.",
                "overlap_score": overlap_score,
            },
        )

    def _layer2_graph_summary(self, project_id: str, stats: dict[str, Any]) -> dict[str, Any]:
        """Build the API summary for a completed Layer 2 graph run."""
        review_queue_count = len(
            [feature for feature in self.db.list_layer2_features(project_id) if feature.status in {"candidate", "needs_review"}]
        )
        return {
            "created_feature_ids": stats["created_feature_ids"],
            "raw_candidate_count": stats["raw_candidate_count"],
            "negative_cache_matches": stats["negative_cache_matches"],
            "duplicate_recommendations": stats["duplicate_recommendations"],
            "review_queue_count": review_queue_count,
            "stop_reason": stats.get("stop_reason", "layer2_graph_review_queue"),
            "total_rounds": stats.get("total_rounds", 0),
        }
