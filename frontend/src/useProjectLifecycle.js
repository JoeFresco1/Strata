import { useState } from "react";

export function useProjectLifecycle({
  apiFetch,
  activeProjectId,
  snapshot,
  applySnapshot,
  refreshProjects,
  setActiveProjectId,
  setActiveTab,
  setError,
  setStatusMessage,
}) {
  const [projectLifecycleState, setProjectLifecycleState] = useState("active");
  const [projectSearchQuery, setProjectSearchQuery] = useState("");
  const [editingProject, setEditingProject] = useState(null);
  const [editProjectName, setEditProjectName] = useState("");
  const [editProjectIdea, setEditProjectIdea] = useState("");
  const [showImportProject, setShowImportProject] = useState(false);
  const [importArchivePath, setImportArchivePath] = useState("");

  function beginEditProject(projectToEdit) {
    setEditingProject(projectToEdit);
    setEditProjectName(projectToEdit.name);
    setEditProjectIdea(projectToEdit.idea);
  }

  async function handleEditProject(event) {
    event.preventDefault();
    if (!editingProject) return;
    setError("");
    try {
      const payload = await apiFetch(`/projects/${editingProject.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: editProjectName, idea: editProjectIdea }),
      });
      setEditingProject(null);
      if (payload.id === activeProjectId && snapshot) {
        applySnapshot({ ...snapshot, project: { ...snapshot.project, ...payload } });
      }
      await refreshProjects();
      setStatusMessage("Project metadata updated.");
    } catch (saveError) {
      setError(saveError.message);
    }
  }

  async function handleCloneProject(projectToClone) {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${projectToClone.id}/clone`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setProjectLifecycleState("active");
      await refreshProjects({ state: "active" });
      setActiveTab("Workspace");
      setActiveProjectId(payload.id);
      setStatusMessage(`Duplicated ${projectToClone.name}.`);
    } catch (cloneError) {
      setError(cloneError.message);
    }
  }

  async function handleArchiveProject(projectToArchive) {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${projectToArchive.id}/archive`, { method: "POST" });
      if (activeProjectId === projectToArchive.id && snapshot) {
        applySnapshot({ ...snapshot, project: { ...snapshot.project, ...payload } });
      }
      await refreshProjects();
      setStatusMessage(`Archived ${projectToArchive.name}.`);
    } catch (archiveError) {
      setError(archiveError.message);
    }
  }

  async function handleUnarchiveProject(projectToUnarchive = snapshot?.project) {
    if (!projectToUnarchive) return;
    setError("");
    try {
      const payload = await apiFetch(`/projects/${projectToUnarchive.id}/unarchive`, { method: "POST" });
      if (activeProjectId === projectToUnarchive.id && snapshot) {
        applySnapshot({ ...snapshot, project: { ...snapshot.project, ...payload } });
      }
      await refreshProjects();
      setStatusMessage(`Unarchived ${projectToUnarchive.name}.`);
    } catch (unarchiveError) {
      setError(unarchiveError.message);
    }
  }

  async function handleImportProject(event) {
    event.preventDefault();
    setError("");
    try {
      const result = await apiFetch("/projects/import", {
        method: "POST",
        body: JSON.stringify({ archive_path: importArchivePath }),
      });
      setShowImportProject(false);
      setImportArchivePath("");
      setProjectLifecycleState("active");
      await refreshProjects({ state: "active" });
      setActiveProjectId(result.project.id);
      setActiveTab("Workspace");
      setStatusMessage(result.lifecycle_warnings?.length ? result.lifecycle_warnings.join(" ") : "Project archive imported.");
    } catch (importError) {
      setError(importError.message);
    }
  }

  async function handleProjectArchiveExport() {
    if (!activeProjectId) return;
    setError("");
    try {
      const result = await apiFetch(`/projects/${activeProjectId}/archive/export`, { method: "POST" });
      setStatusMessage(`Project archive exported: ${result.archive_path}`);
    } catch (exportError) {
      setError(exportError.message);
    }
  }

  return {
    projectLifecycleState,
    setProjectLifecycleState,
    projectSearchQuery,
    setProjectSearchQuery,
    editingProject,
    setEditingProject,
    editProjectName,
    setEditProjectName,
    editProjectIdea,
    setEditProjectIdea,
    showImportProject,
    setShowImportProject,
    importArchivePath,
    setImportArchivePath,
    beginEditProject,
    handleEditProject,
    handleCloneProject,
    handleArchiveProject,
    handleUnarchiveProject,
    handleImportProject,
    handleProjectArchiveExport,
  };
}
