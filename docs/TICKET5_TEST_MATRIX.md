# Ticket 5 Acceptance Test Matrix

This matrix maps each required Ticket 5 test to current automated evidence. Ticket 5-specific tests live in `tests/test_specification_manifest.py` (SQLite/command/API/rendering) and `tests/test_specification_postgres.py` (PostgreSQL 18). Regression evidence comes from the complete `tests/test_core.py` suite and the existing PostgreSQL integration matrix.

| # | Requirement | Automated evidence |
| --- | --- | --- |
| 1 | Exactly one published brief revision | `test_approved_selection_uses_published_root_reviewed_layers_and_active_l3`; `test_missing_or_inaccessible_published_brief_fails_without_manifest` |
| 2 | Deterministic pillar policy | `test_approved_selection_uses_published_root_reviewed_layers_and_active_l3`; `test_layer_ordering_is_deterministic_across_compilations` |
| 3 | Features under excluded pillars excluded | `test_features_under_excluded_pillars_and_cut_or_merged_features_are_excluded` |
| 4 | Cut/merged/superseded excluded | `test_features_under_excluded_pillars_and_cut_or_merged_features_are_excluded` |
| 5 | Only active L3 revision canonical | `test_approved_selection_uses_published_root_reviewed_layers_and_active_l3` |
| 6 | Pending candidate cannot replace active | `test_pending_candidate_never_replaces_active_revision` |
| 7 | Deterministic ordering | `test_layer_ordering_is_deterministic_across_compilations` |
| 8 | Stale pillar blocks approved | `test_stale_pillar_and_feature_block_only_their_identified_branches` |
| 9 | Stale feature blocks affected branch | `test_stale_pillar_and_feature_block_only_their_identified_branches` |
| 10 | Stale L3 blocks approved | `test_stale_layer3_blocks_approved_export_and_remains_visible_as_issue` |
| 11 | Unrelated current branch remains valid | `test_stale_pillar_and_feature_block_only_their_identified_branches` |
| 12 | Mixed brief lineage detected | `test_mixed_brief_lineage_is_detected` |
| 13 | Wrong pillar revision rejected | `test_feature_with_wrong_pillar_revision_dependency_is_rejected` |
| 14 | Wrong feature revision rejected | `test_wrong_layer3_feature_revision_is_detected` |
| 15 | Unknown/inferred policy explicit | `test_inferred_legacy_lineage_is_explicit_and_blocks_approved_mode` |
| 16 | Historical root never receives current descendants | `test_historical_mode_never_substitutes_current_descendants` |
| 17 | Human approval state preserved | `test_approved_selection_uses_published_root_reviewed_layers_and_active_l3` |
| 18 | Critic findings are not decisions | `test_open_critic_finding_is_warning_not_canonical_decision` |
| 19 | Unresolved model findings are warnings only | `test_open_critic_finding_is_warning_not_canonical_decision` |
| 20 | Human L3 selections/fields unchanged | `test_human_owned_layer3_fields_and_selections_are_preserved_verbatim` |
| 21 | Duplicate IDs rejected | `test_duplicate_nested_ids_and_missing_selected_options_are_blocking`; database uniqueness tests |
| 22 | Dangling relationships blocked/excluded | `test_dangling_relationship_is_excluded_with_blocking_issue` |
| 23 | Invalid nested references detected | `test_duplicate_nested_ids_and_missing_selected_options_are_blocking` |
| 24 | Merged artifacts cannot appear twice | `test_features_under_excluded_pillars_and_cut_or_merged_features_are_excluded`; schema uniqueness tests |
| 25 | Selected option must exist | `test_duplicate_nested_ids_and_missing_selected_options_are_blocking` |
| 26 | Compile creates immutable manifest | `test_manifest_rows_reject_in_place_update`; `test_jsonb_constraints_ownership_uniqueness_and_immutability` |
| 27 | Changed source creates new manifest | `test_recompile_after_source_change_creates_new_version_and_keeps_old` |
| 28 | Old manifest unchanged/readable | `test_manifest_payload_survives_later_source_edits_and_removals` |
| 29 | Stable content hash | `test_content_hash_is_stable_across_distinct_compile_records` |
| 30 | Membership/issues match payload | `test_manifest_memberships_and_issues_are_durable_and_ordered`; `test_issue_rows_exactly_match_serialized_manifest` |
| 31 | Concurrent change cannot mix snapshot | `test_project_lock_prevents_mixed_snapshot_during_concurrent_edit`; `test_stale_source_token_conflicts_without_manifest_write` |
| 32 | Idempotent repeat bounded | `test_repeated_compile_submission_is_idempotent`; PostgreSQL idempotency test |
| 33 | JSON conforms to typed schema | `test_json_and_markdown_renderers_use_only_typed_manifest`; API download assertions |
| 34 | Markdown contains all included layers | `test_json_and_markdown_renderers_use_only_typed_manifest` |
| 35 | Both renderers use same membership | Pure renderers accept the same `SpecificationManifestV1`; `test_json_and_markdown_renderers_use_only_typed_manifest` |
| 36 | Renderers do no selection | Pure renderer test plus renderer modules have no database dependency |
| 37 | Old rendering reproducible | `test_old_manifest_render_is_reproducible_after_source_change` |
| 38 | Archive preserves manifests | `test_clone_starts_clean_while_archive_contains_manifest_history` |
| 39 | Clone follows documented clean policy | `test_clone_starts_clean_while_archive_contains_manifest_history`; PostgreSQL lifecycle test |
| 40 | Archive/import historical integrity | `test_archive_import_remaps_manifest_identity_and_preserves_payload` |
| 41 | Import remaps IDs/memberships | `test_archive_import_remaps_manifest_identity_and_preserves_payload` |
| 42 | Purge removes records and outputs | `test_purge_removes_manifest_and_derived_rows`; PostgreSQL lifecycle test |
| 43 | No orphan rows | Purge assertions and PostgreSQL FK/ownership tests |
| 44 | Ticket 1 revision regressions | Complete `tests/test_core.py`; existing PostgreSQL revision matrix |
| 45 | Ticket 2 authority regressions | Complete `tests/test_core.py`; existing PostgreSQL authority matrix |
| 46 | Ticket 3 command regressions | Complete `tests/test_core.py`; existing PostgreSQL command matrix |
| 47 | Ticket 4 freshness regressions | Complete `tests/test_core.py`; existing PostgreSQL dependency matrix |
| 48 | Diagnostic L2/L3 exports remain | Existing Layer 2/3 API/export tests in `tests/test_core.py`; compatibility routes retained and explicitly labeled diagnostic |

The PostgreSQL matrix additionally validates migration v7 application/idempotency, JSONB payloads, deferred cross-project ownership, immutable rows, membership uniqueness, issue ownership, every command failure-injection stage, concurrent project locking, lifecycle remapping, and disposable-database cleanup.
