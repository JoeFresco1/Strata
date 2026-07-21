import { useEffect, useId, useRef, useState } from "react";
import "./ProjectShell.css";

function formatExactDate(value) {
  if (!value) return "Never";
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatRelativeDate(value) {
  if (!value) return "Never opened";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  const today = new Date();
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDelta = Math.round((startOfDate - startOfToday) / 86400000);
  if (dayDelta === 0) return "today";
  if (dayDelta === -1) return "yesterday";
  if (dayDelta > -7 && dayDelta < 0) return `${Math.abs(dayDelta)} days ago`;
  return formatExactDate(value);
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
  const view = lifecycleState === "all" ? "total" : lifecycleState;
  if (trimmedSearch) {
    return `${count} ${noun} matching "${trimmedSearch}"`;
  }
  return `${count} ${view} ${noun}`;
}

function ProjectLibraryToolbar({
  lifecycleState,
  onLifecycleStateChange,
  sortOrder,
  onSortOrderChange,
  searchQuery,
  onSearchQueryChange,
  onCreateProject,
  onImportProject,
}) {
  const [draftSearch, setDraftSearch] = useState(searchQuery);
  const trimmedDraftSearch = draftSearch.trim();

  useEffect(() => {
    setDraftSearch(searchQuery);
  }, [searchQuery]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (draftSearch !== searchQuery) onSearchQueryChange(draftSearch);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [draftSearch, onSearchQueryChange, searchQuery]);

  function clearSearch() {
    setDraftSearch("");
    onSearchQueryChange("");
  }

  return (
    <div className="library-toolbar">
      <div className="library-filter-bar" aria-label="Project library filters">
        <div className="project-search-wrap">
          <input
            className="project-search"
            value={draftSearch}
            onChange={(event) => setDraftSearch(event.target.value)}
            placeholder="Search by project name, description, or ID..."
            aria-label="Search projects by name, description, or ID"
          />
          {trimmedDraftSearch ? (
            <button type="button" className="project-search-clear" onClick={clearSearch} aria-label="Clear project search" title="Clear project search">
              Clear
            </button>
          ) : null}
        </div>
        <label className="compact-select library-select">
          <span>View</span>
          <select value={lifecycleState} onChange={(event) => onLifecycleStateChange(event.target.value)} aria-label="Project view">
            <option value="active">{viewLabel("active")}</option>
            <option value="archived">{viewLabel("archived")}</option>
            <option value="all">{viewLabel("all")}</option>
          </select>
        </label>
        <label className="compact-select library-select">
          <span>Sort</span>
          <select value={sortOrder} onChange={(event) => onSortOrderChange(event.target.value)} aria-label="Project sort">
            <option value="updated">{sortLabel("updated")}</option>
            <option value="last_opened">{sortLabel("last_opened")}</option>
            <option value="newest">{sortLabel("newest")}</option>
            <option value="oldest">{sortLabel("oldest")}</option>
            <option value="name">{sortLabel("name")}</option>
          </select>
        </label>
      </div>
      <div className="library-primary-actions">
        <button type="button" onClick={onCreateProject}>Create new project</button>
        <button type="button" className="secondary-button" onClick={onImportProject}>Import</button>
      </div>
    </div>
  );
}

function ProjectCardActions({ project, onEditProject, onCloneProject, onArchiveProject, onUnarchiveProject }) {
  const [open, setOpen] = useState(false);
  const menuId = useId();

  function handleArchive() {
    const confirmed = window.confirm(`Archive "${project.name}"? You can restore it from the archived view.`);
    if (confirmed) onArchiveProject(project);
    setOpen(false);
  }

  function handleUnarchive() {
    onUnarchiveProject(project);
    setOpen(false);
  }

  return (
    <div
      className="project-card-secondary-actions"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === "Escape") setOpen(false);
      }}
    >
      <button
        type="button"
        className="secondary-button project-card-menu-trigger"
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={`More actions for ${project.name}`}
        onClick={() => setOpen((current) => !current)}
      >
        More
      </button>
      {open ? (
        <div id={menuId} className="project-card-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => { onCloneProject(project); setOpen(false); }}>Duplicate</button>
          <button type="button" role="menuitem" onClick={() => { onEditProject(project); setOpen(false); }}>Rename or edit</button>
          {project.lifecycle_state === "archived" ? (
            <button type="button" role="menuitem" onClick={handleUnarchive}>Unarchive</button>
          ) : (
            <button type="button" role="menuitem" className="project-danger-action" onClick={handleArchive}>Archive</button>
          )}
        </div>
      ) : null}
    </div>
  );
}

function ProjectCard({ project, onOpenProject, onEditProject, onCloneProject, onArchiveProject, onUnarchiveProject }) {
  const updatedAt = project.updated_at || project.brief_updated_at || project.created_at;
  const openedAt = project.last_opened_at;
  const leadingDate = openedAt
    ? { label: "Opened", value: formatRelativeDate(openedAt), title: formatExactDate(openedAt) }
    : { label: "Updated", value: formatRelativeDate(updatedAt), title: formatExactDate(updatedAt) };
  const mapSummary = `${project.node_count || 0} nodes · ${project.pillar_count || 0} pillars`;
  const status = project.brief_status || "draft";

  return (
    <article
      className={`project-card ${project.lifecycle_state === "archived" ? "archived" : ""}`}
      onClick={() => onOpenProject(project.id)}
      title={`Project ID: ${project.id}`}
    >
      <div className="project-card-head">
        <div className="project-title-row">
          <strong>{project.name}</strong>
          <span className={`status-pill project-brief-status ${status}`}>{status}</span>
          {project.lifecycle_state === "archived" ? <span className="status-pill archived">archived</span> : null}
        </div>
      </div>
      <p className="project-card-description">{project.idea}</p>
      <div className="project-card-meta" aria-label={`${project.name} metadata`}>
        <span title={leadingDate.title}>{leadingDate.label} {leadingDate.value}</span>
        <span>{mapSummary}</span>
        {project.source_project_name ? <span className="project-source-note">Cloned from {project.source_project_name}</span> : null}
      </div>
      <div className="project-card-actions">
        <button type="button" onClick={(event) => { event.stopPropagation(); onOpenProject(project.id); }}>Open</button>
        <ProjectCardActions
          project={project}
          onEditProject={onEditProject}
          onCloneProject={onCloneProject}
          onArchiveProject={onArchiveProject}
          onUnarchiveProject={onUnarchiveProject}
        />
      </div>
    </article>
  );
}

function ProjectGrid({ projects, resultSummary, ...actions }) {
  return (
    <div className="project-grid" aria-label={resultSummary}>
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} {...actions} />
      ))}
    </div>
  );
}

function ProjectEmptyState({ trimmedSearch, lifecycleState, onSearchQueryChange, onCreateProject, onImportProject }) {
  const isSearchEmpty = Boolean(trimmedSearch);
  return (
    <div className="panel library-empty-state">
      <strong>{isSearchEmpty ? "No projects match your search" : lifecycleState === "archived" ? "No archived projects" : "No projects yet"}</strong>
      <p className="muted">
        {isSearchEmpty
          ? `No ${viewLabel(lifecycleState).toLowerCase()} match "${trimmedSearch}".`
          : "Create your first project or import an archive to get started."}
      </p>
      <div className="button-row compact">
        {isSearchEmpty ? <button type="button" className="secondary-button" onClick={() => onSearchQueryChange("")}>Clear search</button> : null}
        <button type="button" onClick={onCreateProject}>Create new project</button>
        {!isSearchEmpty ? <button type="button" className="secondary-button" onClick={onImportProject}>Import archive</button> : null}
      </div>
    </div>
  );
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
  errorMessage = "",
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
        <ProjectLibraryToolbar
          lifecycleState={lifecycleState}
          onLifecycleStateChange={onLifecycleStateChange}
          sortOrder={sortOrder}
          onSortOrderChange={onSortOrderChange}
          searchQuery={searchQuery}
          onSearchQueryChange={onSearchQueryChange}
          onCreateProject={onCreateProject}
          onImportProject={onImportProject}
        />
      </div>
      <div className="library-status-row" aria-live="polite">
        <span className="library-status-count">{loading ? "Loading projects..." : resultSummary}</span>
        <span className="library-status-meta" aria-label="Current project filters">
          <span className="status-pill library-status-pill">{viewLabel(lifecycleState)}</span>
          <span className="status-pill library-status-pill">{sortLabel(sortOrder)}</span>
        </span>
      </div>
      {errorMessage && !loading ? (
        <div className="library-error-state" role="status">
          <strong>Projects could not refresh.</strong>
          <span>{errorMessage}</span>
        </div>
      ) : null}
      {loading ? (
        <div className="project-grid" aria-label="Loading projects">
          {[0, 1, 2, 3, 4, 5].map((item) => (
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
        <ProjectGrid
          projects={projects}
          resultSummary={resultSummary}
          onOpenProject={onOpenProject}
          onEditProject={onEditProject}
          onCloneProject={onCloneProject}
          onArchiveProject={onArchiveProject}
          onUnarchiveProject={onUnarchiveProject}
        />
      ) : (
        <ProjectEmptyState
          trimmedSearch={trimmedSearch}
          lifecycleState={lifecycleState}
          onSearchQueryChange={onSearchQueryChange}
          onCreateProject={onCreateProject}
          onImportProject={onImportProject}
        />
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
