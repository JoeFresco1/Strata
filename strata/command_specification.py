from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from strata.command_types import (
    CommandValidationError,
    CompileSpecificationManifest,
    RenderSpecificationManifest,
    StaleEffect,
)
from strata.specification_compiler import SpecificationCompiler
from strata.specification_models import CompilationMode
from strata.specification_render import RENDERER_VERSION, render_specification_json, render_specification_markdown


class CommandSpecificationMixin:
    """Command handlers for durable specification compilation and rendering."""

    def _compile_specification(self, command: CompileSpecificationManifest) -> Any:
        project = self.db.get_project(command.project_id)

        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            self._assert_expected(command, self.specification_source_state_token(command.project_id), project.id)
            command_id = str(self.db._transaction_state.command_id)
            manifest = SpecificationCompiler(self.db).compile(
                project_id=command.project_id, mode=CompilationMode(command.mode),
                actor=command.actor.actor_id, origin=command.actor.origin.value, command_id=command_id,
                historical_brief_revision_id=command.historical_brief_revision_id,
            )
            self.db.insert_specification_manifest(manifest)
            return {"manifest": manifest.model_dump(mode="json")}, self.specification_source_state_token(command.project_id), StaleEffect()

        return self._execute(command, target_type="specification_manifest", target_id="new", operation=operation, allow_archived=True)

    def _render_specification(self, command: RenderSpecificationManifest) -> Any:
        project = self.db.get_project(command.project_id)
        manifest = self.db.get_specification_manifest(command.project_id, command.manifest_id)
        formats = tuple(dict.fromkeys(command.formats))
        if not formats or any(item not in {"json", "markdown"} for item in formats):
            raise CommandValidationError("At least one supported render format is required.")

        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            self._assert_expected(command, manifest.content_hash, manifest.manifest_id)
            command_id = str(self.db._transaction_state.command_id)
            slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(manifest.project.get("name", ""))).strip("-") or manifest.project_id
            target_dir = Path(self.services.config.exports_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            rendered: dict[str, str] = {}
            for format_name in formats:
                content = render_specification_json(manifest) if format_name == "json" else render_specification_markdown(manifest)
                suffix = "json" if format_name == "json" else "md"
                path = target_dir / f"{slug}-specification-v{manifest.sequence_number}.{suffix}"
                path.write_text(content, encoding="utf-8")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                self.db.insert_rendered_specification_artifact(
                    manifest_id=manifest.manifest_id, project_id=manifest.project_id, format=format_name,
                    renderer_version=RENDERER_VERSION, content_hash=digest, path=str(path), command_id=command_id,
                )
                rendered[f"{format_name}_path"] = str(path)
            return {"manifest_id": manifest.manifest_id, "manifest_version": manifest.sequence_number, "rendered": rendered}, manifest.content_hash, StaleEffect()

        return self._execute(command, target_type="specification_render", target_id=command.manifest_id, operation=operation, allow_archived=True)
