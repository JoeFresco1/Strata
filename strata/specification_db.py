from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from strata.specification_models import SpecificationManifestV1


def utc_now() -> str:
    """Return a portable UTC timestamp without importing the composite database."""
    return datetime.now(timezone.utc).isoformat()


class SpecificationDatabaseMixin:
    """Persist immutable specification manifests and their derived artifacts."""

    def next_specification_sequence(self, project_id: str) -> int:
        """Allocate the next project-local manifest sequence while the project command lock is held."""
        row = self._fetchone(
            f"SELECT COALESCE(MAX(sequence_number), 0) AS value FROM specification_manifests WHERE project_id = {self.param}",
            (project_id,),
        )
        return int(row["value"]) + 1

    def insert_specification_manifest(self, manifest: SpecificationManifestV1) -> None:
        """Insert a manifest, ordered memberships, and issues as one ambient transaction."""
        payload = manifest.model_dump(mode="json")
        self._execute(
            f"""
            INSERT INTO specification_manifests (
                id, project_id, sequence_number, schema_version, mode, policy_version, status,
                selected_brief_revision_id, root_content_hash, content_hash, exportable,
                actor, origin, command_id, payload, created_at
            ) VALUES ({', '.join([self.param] * 16)})
            """,
            (
                manifest.manifest_id, manifest.project_id, manifest.sequence_number, manifest.schema_version,
                manifest.mode.value, manifest.compilation_policy_version, manifest.status,
                str(manifest.root_lineage.get("brief_revision_id", "")),
                str(manifest.root_lineage.get("content_hash", "")), manifest.content_hash,
                manifest.exportable, manifest.actor, manifest.origin, manifest.command_id,
                self._dump_json(payload), manifest.created_at.isoformat(),
            ),
        )
        for membership in manifest.memberships:
            value = membership.model_dump(mode="json")
            self._execute(
                f"""
                INSERT INTO specification_manifest_memberships (
                    id, manifest_id, project_id, layer, artifact_type, logical_artifact_id,
                    artifact_revision, content_token, inclusion_reason, ordinal,
                    dependency_metadata, authority_metadata, created_at
                ) VALUES ({', '.join([self.param] * 13)})
                """,
                (
                    str(uuid.uuid4()), manifest.manifest_id, manifest.project_id, value["layer"],
                    value["artifact_type"], value["logical_artifact_id"], value["artifact_revision"],
                    value["content_token"], value["inclusion_reason"], value["ordinal"],
                    self._dump_json(value["dependency_metadata"]), self._dump_json(value["authority_metadata"]),
                    manifest.created_at.isoformat(),
                ),
            )
        for ordinal, issue in enumerate(manifest.issues):
            value = issue.model_dump(mode="json")
            self._execute(
                f"""
                INSERT INTO specification_manifest_issues (
                    id, manifest_id, project_id, ordinal, issue_code, stage, severity, message,
                    artifact_type, artifact_id, artifact_revision, details, created_at
                ) VALUES ({', '.join([self.param] * 13)})
                """,
                (
                    str(uuid.uuid4()), manifest.manifest_id, manifest.project_id, ordinal, value["code"],
                    value["stage"], value["severity"], value["message"], value["artifact_type"],
                    value["artifact_id"], value["artifact_revision"], self._dump_json(value["details"]),
                    manifest.created_at.isoformat(),
                ),
            )

    def get_specification_manifest(self, project_id: str, manifest_id: str) -> SpecificationManifestV1:
        """Read and validate one immutable manifest owned by a project."""
        row = self._fetchone(
            f"SELECT payload FROM specification_manifests WHERE project_id = {self.param} AND id = {self.param}",
            (project_id, manifest_id),
        )
        if row is None:
            raise ValueError(f"Specification manifest not found: {manifest_id}")
        return SpecificationManifestV1.model_validate(self._load_json(row["payload"]))

    def list_specification_manifests(self, project_id: str) -> list[dict[str, Any]]:
        """Return durable manifest headers newest first without duplicating full payloads."""
        rows = self._fetchall(
            f"""
            SELECT id, project_id, sequence_number, schema_version, mode, policy_version, status,
                   selected_brief_revision_id, content_hash, exportable, actor, origin, command_id, created_at, payload
            FROM specification_manifests WHERE project_id = {self.param}
            ORDER BY sequence_number DESC
            """,
            (project_id,),
        )
        values = []
        for row in rows:
            value = dict(row)
            payload = self._load_json(value.pop("payload"))
            value["imported_historical"] = bool(payload.get("imported_historical", False))
            value["import_metadata"] = payload.get("import_metadata", {})
            values.append(value)
        return values

    def insert_rendered_specification_artifact(
        self, *, manifest_id: str, project_id: str, format: str, renderer_version: str,
        content_hash: str, path: str, command_id: str,
    ) -> dict[str, Any]:
        """Record one immutable renderer result and return its durable row."""
        artifact_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO specification_rendered_artifacts (
                id, manifest_id, project_id, format, renderer_version, content_hash, path, command_id, created_at
            ) VALUES ({', '.join([self.param] * 9)})
            """,
            (artifact_id, manifest_id, project_id, format, renderer_version, content_hash, path, command_id, now),
        )
        return dict(self._fetchone(f"SELECT * FROM specification_rendered_artifacts WHERE id = {self.param}", (artifact_id,)))

    def get_rendered_specification_artifact(self, project_id: str, manifest_id: str, format: str) -> dict[str, Any]:
        """Return the latest stored renderer record for a project-owned manifest and format."""
        row = self._fetchone(
            f"""
            SELECT * FROM specification_rendered_artifacts
            WHERE project_id = {self.param} AND manifest_id = {self.param} AND format = {self.param}
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id, manifest_id, format),
        )
        if row is None:
            raise ValueError(f"Rendered {format} artifact not found for manifest: {manifest_id}")
        return dict(row)
