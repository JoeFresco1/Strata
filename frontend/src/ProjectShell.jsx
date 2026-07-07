import { useEffect, useId, useRef } from "react";
import "./ProjectShell.css";

// Formats project timestamps consistently inside the project library.
function formatProjectCardDate(value) {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
}

function viewLabel(state) {
  return {
    active: "Active projects",
    archived: "Archived projects",
    all: "All projects",
  }[state] || "Active projects";
}

function sortLabel(sortOrder) {
  return {
    updated: "Recently updated",
    last_opened: "Recently opened",
    newest: "Newest created",
    oldest: "Oldest created",
    name: "Name",
  }[sortOrder] || "Recently updated";
}

function projectResultSummary(projects, lifecycleState, trimmedSearch) {
  const count = projects.length;
  const noun = count === 1 ? "project" : "projects";
  const view = viewLabel(lifecycleState).toLowerCase();
  if (trimmedSearch) {
    return `${count} ${noun} matching "${trimmedSearch}" in ${view}.`;
  }
  return `${count} ${view.toLowerCase()}.`;
}

export function ProjectHub({
  projects,
  loading = false,
  sortOrder,
  onSortOrderChange,
  lifecycleState,
  onLifecycleStateChange,
  searchQuery,
  onSearchQueryChange,
  onOpenProject,
  onCreateProject,
  onEditProject,
  onCloneProject,
  onArchiveProject,
  onUnarchiveProject,
  onImportProject,
}) {
  const trimmedSearch = searchQuery.trim();
  const resultSummary = projectResultSummary(projects, lifecycleState, trimmedSearch);
  // ProjectHub is the landing workspace for opening or creating Strata projects.
  return (
    <section className="project-hub" aria-busy={loading ? "true" : undefined}>
      <div className="hub-header">
        <div className="hub-heading">
          <h1>Project Library</h1>
          <p className="muted">Open a project to keep building, or create a new one and jump straight into Layer 0.</p>
        </div>
        <div className="hub-toolbar">
          <div className="library-control-row">
            <label className="compact-select">
              View
              <select value={lifecycleState} onChange={(event) => onLifecycleStateChange(event.target.value)} aria-label="Project view">
                <option value="active">{viewLabel("active")}</option>
                <option value="archived">{viewLabel("archived")}</option>
                <option value="all">{viewLabel("all")}</option>
              </select>
            </label>
            <label className="compact-select">
              Sort
              <select value={sortOrder} onChange={(event) => onSortOrderChange(event.target.value)} aria-label="Project sort">
                <option value="updated">{sortLabel("updated")}</option>
                <option value="last_opened">{sortLabel("last_opened")}</option>
                <option value="newest">{sortLabel("newest")}</option>
                <option value="oldest">{sortLabel("oldest")}</option>
                <option value="name">{sortLabel("name")}</option>
              </select>
            </label>
          </div>
          <div className="hub-actions">
            <div className="library-command-row">
              <button type="button" onClick={onCreateProject}>Create new project</button>
              <details className="library-menu">
                <summary aria-label="More library actions" title="More library actions">More</summary>
                <div className="library-menu-panel">
                  <button type="button" className="secondary-button" onClick={onImportProject}>Import Project Archive</button>
                </div>
              </details>
            </div>
            <div className="project-search-wrap">
              <input className="project-search" value={searchQuery} onChange={(event) => onSearchQueryChange(event.target.value)} placeholder="Search projects" aria-label="Search projects" />
              {trimmedSearch ? (
                <button type="button" className="project-search-clear" onClick={() => onSearchQueryChange("")} aria-label="Clear project search" title="Clear project search">
                  x
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
      <div className="library-status-row" aria-live="polite">
        <span>{loading ? "Loading projects..." : resultSummary}</span>
        <span>{viewLabel(lifecycleState)} | {sortLabel(sortOrder)}</span>
      </div>
      {loading ? (
        <div className="project-grid" aria-label="Loading projects">
          {[0, 1, 2].map((item) => (
            <article key={item} className="project-card project-card-skeleton" aria-hidden="true">
              <div className="project-skeleton-line title" />
              <div className="project-skeleton-line" />
              <div className="project-skeleton-line short" />
              <div className="project-skeleton-actions">
                <span />
                <span />
              </div>
            </article>
          ))}
        </div>
      ) : projects.length ? (
        <div className="project-grid" aria-label={resultSummary}>
          {projects.map((project) => (
            <article key={project.id} className={`project-card ${project.lifecycle_state === "archived" ? "archived" : ""}`}>
              <div className="project-card-head">
                <div className="project-title-row">
                  <strong>{project.name}</strong>
                  <button type="button" className="icon-button project-title-edit" onClick={() => onEditProject(project)} aria-label={`Edit name and library summary for ${project.name}`} title="Edit name and summary">
                    <svg aria-hidden="true" className="project-title-edit-mark" viewBox="0 0 16 16" focusable="false">
                      <path d="M3 11.8 3.7 9l6.9-6.9a1.7 1.7 0 0 1 2.4 0l.9.9a1.7 1.7 0 0 1 0 2.4L7 12.3l-2.8.7H3v-1.2Zm1.7-.3 1.5-.4 6.8-6.8a.3.3 0 0 0 0-.4l-.9-.9a.3.3 0 0 0-.4 0L4.9 9.8l-.4 1.5.2.2Z" />
                    </svg>
                  </button>
                </div>
                <div className="project-status-row">
                  {project.lifecycle_state === "archived" ? <span className="status-pill archived">archived</span> : null}
                  <span className={`status-pill ${project.brief_status || "draft"}`}>{project.brief_status || "draft"}</span>
                </div>
              </div>
              <p>{project.idea}</p>
              <div className="project-card-meta">
                <span><strong>Updated</strong> {formatProjectCardDate(project.updated_at || project.brief_updated_at || project.created_at)}</span>
                <span><strong>Opened</strong> {formatProjectCardDate(project.last_opened_at)}</span>
                <span><strong>Map</strong> {project.node_count || 0} nodes | {project.pillar_count || 0} pillars</span>
                {project.source_project_name ? <span>Cloned from {project.source_project_name}</span> : null}
                <span>Project {project.id.slice(0, 8)}</span>
              </div>
              <div className="project-card-actions">
                <button type="button" onClick={() => onOpenProject(project.id)}>Open</button>
                <button type="button" className="secondary-button" onClick={() => onCloneProject(project)}>Duplicate</button>
                {project.lifecycle_state === "archived" ? (
                  <button type="button" className="secondary-button" onClick={() => onUnarchiveProject(project)}>Unarchive</button>
                ) : (
                  <button type="button" className="secondary-button" onClick={() => onArchiveProject(project)}>Archive</button>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="panel library-empty-state">
          <strong>{trimmedSearch ? "No matching projects" : lifecycleState === "archived" ? "No archived projects" : "No projects yet"}</strong>
          <p className="muted">
            {trimmedSearch
              ? `No ${viewLabel(lifecycleState).toLowerCase()} match "${trimmedSearch}". Clear the search or switch views to keep looking.`
              : "Create the first project to capture a product idea and begin Layer 0 planning."}
          </p>
          <div className="button-row compact">
            {trimmedSearch ? <button type="button" className="secondary-button" onClick={() => onSearchQueryChange("")}>Clear Search</button> : null}
            <button type="button" onClick={onCreateProject}>Create new project</button>
          </div>
        </div>
      )}
    </section>
  );
}

export function ModalFrame({ title, subtitle, onClose, children, className = "", initialFocusSelector = "" }) {
  // Shared modal shell keeps settings, guide, and create-project dialogs consistent.
  const titleId = useId();
  const subtitleId = useId();
  const dialogRef = useRef(null);

  useEffect(() => {
    const previousActiveElement = document.activeElement;
    const preferredFocusTarget = initialFocusSelector
      ? dialogRef.current?.querySelector(initialFocusSelector)
      : null;
    const fallbackFocusTarget = dialogRef.current?.querySelector(
      "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
    );
    const focusTarget = preferredFocusTarget || fallbackFocusTarget;
    focusTarget?.focus?.();
    return () => previousActiveElement?.focus?.();
  }, [initialFocusSelector]);

  function handleDialogKeyDown(event) {
    if (event.key === "Escape") {
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll(
      "button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])",
    ) || []);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        ref={dialogRef}
        className={`modal-shell ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={subtitle ? subtitleId : undefined}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleDialogKeyDown}
      >
        <div className="modal-header">
          <div>
            <h2 id={titleId}>{title}</h2>
            {subtitle ? <p id={subtitleId} className="muted">{subtitle}</p> : null}
          </div>
          <button type="button" className="secondary-button" onClick={onClose}>Close</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function CreateProjectModal({ name, idea, onNameChange, onIdeaChange, onSubmit, onClose }) {
  // Captures the minimum project seed needed before Layer 0 planning starts.
  return (
    <ModalFrame
      title="Create new project"
      subtitle="Name the project, capture the product idea, and jump right into Layer 0."
      onClose={onClose}
      className="compact-modal"
      initialFocusSelector="[data-modal-initial-focus]"
    >
      <form className="modal-form" onSubmit={onSubmit}>
        <label>
          Name
          <input value={name} onChange={(event) => onNameChange(event.target.value)} data-modal-initial-focus />
        </label>
        <label>
          Product Idea
          <textarea value={idea} onChange={(event) => onIdeaChange(event.target.value)} rows={6} />
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" disabled={!name.trim() || !idea.trim()}>Create project</button>
        </div>
      </form>
    </ModalFrame>
  );
}

export function EditProjectModal({ project, name, idea, onNameChange, onIdeaChange, onSubmit, onClose }) {
  return (
    <ModalFrame
      title="Edit project"
      subtitle="These fields shape the library card only. Published Layer 0 brief content is unchanged."
      onClose={onClose}
      className="compact-modal"
      initialFocusSelector="[data-modal-initial-focus]"
    >
      <form className="modal-form" onSubmit={onSubmit}>
        <label>
          Name
          <input value={name} onChange={(event) => onNameChange(event.target.value)} data-modal-initial-focus />
        </label>
        <label>
          Library Summary
          <textarea value={idea} onChange={(event) => onIdeaChange(event.target.value)} rows={6} />
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" disabled={!name.trim() || !idea.trim() || (name === project.name && idea === project.idea)}>Save</button>
        </div>
      </form>
    </ModalFrame>
  );
}

export function ImportProjectModal({ archivePath, onArchivePathChange, onSubmit, onClose }) {
  return (
    <ModalFrame
      title="Import project archive"
      subtitle="Import creates a new project ID and keeps the source archive intact."
      onClose={onClose}
      className="compact-modal"
      initialFocusSelector="[data-modal-initial-focus]"
    >
      <form className="modal-form" onSubmit={onSubmit}>
        <div className="import-schema-note">
          <strong>Expected archive</strong>
          <span>Use a Strata project archive zip containing manifest.json, project.json, and tables/*.json. Import creates a separate project and keeps the archive unchanged.</span>
        </div>
        <label>
          Archive path
          <input value={archivePath} onChange={(event) => onArchivePathChange(event.target.value)} placeholder="C:\\path\\to\\project-archive.zip" data-modal-initial-focus />
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" disabled={!archivePath.trim()}>Import</button>
        </div>
      </form>
    </ModalFrame>
  );
}
