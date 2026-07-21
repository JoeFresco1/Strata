from __future__ import annotations

import uuid
from pathlib import Path

from strata.command_types import (
    ActorType,
    ArchiveProject,
    CommandNotFoundError,
    CommandResult,
    HumanAuthorityRequiredError,
    ImportProjectArchive,
    StaleEffect,
    UnarchiveProject,
    UpdateProjectMetadata,
    state_token,
)


class CommandLifecycleMixin:
    """Keep project lifecycle commands small while sharing the core command unit of work."""

    def _update_project_metadata(self, command: UpdateProjectMetadata) -> CommandResult:
        """Update project library metadata under the canonical concurrency boundary."""
        def operation():
            project = self.db.get_project(command.project_id)
            self._assert_expected(command, self.project_state_token(project), project.id)
            updated = self.db.update_project_metadata(project.id, name=command.name.strip(), idea=command.idea.strip())
            return {"project": updated.model_dump(mode="json")}, self.project_state_token(updated), StaleEffect()
        return self._execute(command, target_type="project", target_id=command.project_id, operation=operation)

    def _archive_project(self, command: ArchiveProject) -> CommandResult:
        """Archive a project and its command audit in one transaction."""
        def operation():
            project = self.db.get_project(command.project_id)
            self._assert_expected(command, self.project_state_token(project), project.id)
            archived = self.db.archive_project(project.id)
            return {"project": archived.model_dump(mode="json")}, self.project_state_token(archived), StaleEffect()
        return self._execute(command, target_type="project", target_id=command.project_id, operation=operation, allow_archived=True)

    def _unarchive_project(self, command: UnarchiveProject) -> CommandResult:
        """Reactivate an archived project under optimistic concurrency."""
        def operation():
            project = self.db.get_project(command.project_id)
            self._assert_expected(command, self.project_state_token(project), project.id)
            active = self.db.unarchive_project(project.id)
            return {"project": active.model_dump(mode="json")}, self.project_state_token(active), StaleEffect()
        return self._execute(command, target_type="project", target_id=command.project_id, operation=operation, allow_archived=True)

    def _import_archive(self, command: ImportProjectArchive) -> CommandResult:
        """Run the documented bulk-import exception with a trusted import actor."""
        if command.actor.actor_type is not ActorType.IMPORT:
            raise HumanAuthorityRequiredError("Project archive import requires a trusted import actor.")
        path = Path(command.archive_path)
        if not path.exists():
            raise CommandNotFoundError(f"Project archive not found: {path}")
        result = self.db.import_project_archive(path)
        project = result["project"]
        return CommandResult(
            command_id=str(uuid.uuid4()), command_type=type(command).__name__, project_id=project.id,
            target_type="project", target_id=project.id,
            state_token=state_token(project.model_dump(mode="json")),
            data={"project": project.model_dump(mode="json"), "lifecycle_warnings": result.get("lifecycle_warnings", [])},
            stale_effect=StaleEffect(), idempotent=False,
        )
