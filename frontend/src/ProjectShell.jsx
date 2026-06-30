import "./ProjectShell.css";

const GUIDE_SECTIONS = [
  {
    heading: "Start And Orient",
    sections: [
      {
        title: "Start a project",
        body: "Use the library to create, open, duplicate, archive, unarchive, import, or export portable project archives.",
      },
      {
        title: "Choose the work style",
        body: "Start in Layer 0 Plan mode for guided intake or Form mode if you already know the structure you want.",
      },
      {
        title: "Check project behavior",
        body: "Project Settings control compute mode, research, and assistant behavior for one project without changing app-wide defaults.",
      },
    ],
  },
  {
    heading: "Move Through The Layers",
    sections: [
      {
        title: "Layer 0 brief",
        body: "Shape one canonical product brief and publish it when you want downstream generation and research to unlock.",
      },
      {
        title: "Layer 1 pillars",
        body: "Generate or manually add major product pillars, then keep, cut, merge, rename, prioritize, and review coverage before expanding.",
      },
      {
        title: "Layer 2 workspace",
        body: "Turn approved pillars into concrete capabilities using the map, table, inspector, manual feature entry, bulk review, relationships, and evidence panels.",
      },
      {
        title: "Layer 3 Capability Design",
        body: "Expand approved Layer 2 features into product-level cards with behavior, configuration, decisions, risks, readiness, and optional cited competitive analysis.",
      },
    ],
  },
  {
    heading: "Export And Troubleshoot",
    sections: [
      {
        title: "Delivery and exports",
        body: "Create Layer 2 exports, full project bundles, portable archives, diagnostics bundles, and Spec Kit-ready delivery handoff zips.",
      },
      {
        title: "Provider readiness",
        body: "If model-backed controls are blocked, check provider readiness first. Tokens stay server-side and the browser only sees safe status.",
      },
      {
        title: "Analytics and diagnostics",
        body: "Use Analytics for model calls, queue state, and runtime health. Open diagnostics when you need traces, logs, or a redaction preview.",
      },
      {
        title: "Assistant",
        body: "Use the project assistant from any tab for cited synthesis, navigation, durable conversations, deeper specialist analysis, and action proposals.",
      },
      {
        title: "Data ownership",
        body: "Project data is keep-by-default. Backup, restore, archive, import/export, cleanup, purge dry-runs, and artifact previews are explicit actions.",
      },
    ],
  },
];

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
  // ProjectHub is the landing workspace for opening or creating Strata projects.
  return (
    <section className="project-hub">
      <div className="hub-header">
        <div>
          <h1>Project Library</h1>
          <p className="muted">Open a project to keep building, or create a new one and jump straight into Layer 0.</p>
        </div>
        <div className="hub-actions">
          <div className="project-search-wrap">
            <input className="project-search" value={searchQuery} onChange={(event) => onSearchQueryChange(event.target.value)} placeholder="Search projects" aria-label="Search projects" />
            {trimmedSearch ? (
              <button type="button" className="project-search-clear" onClick={() => onSearchQueryChange("")} aria-label="Clear project search" title="Clear project search">
                x
              </button>
            ) : null}
          </div>
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
          <div className="library-command-row">
            <button type="button" onClick={onCreateProject}>Create New Project</button>
            <details className="library-menu">
              <summary aria-label="More library actions" title="More library actions">More</summary>
              <div className="library-menu-panel">
                <button type="button" className="secondary-button" onClick={onImportProject}>Import Project Archive</button>
              </div>
            </details>
          </div>
        </div>
      </div>
      {loading ? (
        <div className="project-grid" aria-label="Loading projects">
          {[0, 1, 2].map((item) => <div key={item} className="project-card project-card-skeleton" />)}
        </div>
      ) : projects.length ? (
        <div className="project-grid">
          {projects.map((project) => (
            <article key={project.id} className={`project-card ${project.lifecycle_state === "archived" ? "archived" : ""}`}>
              <div className="project-card-head">
                <div className="project-title-row">
                  <strong>{project.name}</strong>
                  <button type="button" className="icon-button project-title-edit" onClick={() => onEditProject(project)} aria-label={`Edit library details for ${project.name}`} title="Edit library details">
                    Edit
                  </button>
                </div>
                <div className="button-row compact">
                  {project.lifecycle_state === "archived" ? <span className="status-pill archived">archived</span> : null}
                  <span className={`status-pill ${project.brief_status || "draft"}`}>{project.brief_status || "draft"}</span>
                </div>
              </div>
              <p>{project.idea}</p>
              <div className="project-card-meta">
                <span>Updated {formatProjectCardDate(project.updated_at || project.brief_updated_at || project.created_at)}</span>
                <span>Opened {formatProjectCardDate(project.last_opened_at)}</span>
                <span>{project.node_count || 0} nodes</span>
                <span>{project.pillar_count || 0} pillars</span>
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
        <div className="panel">
          <p className="muted">
            {trimmedSearch ? `No ${viewLabel(lifecycleState).toLowerCase()} match "${trimmedSearch}".` : "No projects yet. Use the Create New Project button to start the first brief."}
          </p>
        </div>
      )}
    </section>
  );
}

export function ModalFrame({ title, subtitle, onClose, children, className = "" }) {
  // Shared modal shell keeps settings, guide, and create-project dialogs consistent.
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div className={`modal-shell ${className}`.trim()} role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>{title}</h2>
            {subtitle ? <p className="muted">{subtitle}</p> : null}
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
      title="Create New Project"
      subtitle="Name the project, capture the product idea, and jump right into Layer 0."
      onClose={onClose}
      className="compact-modal"
    >
      <form className="modal-form" onSubmit={onSubmit}>
        <label>
          Name
          <input value={name} onChange={(event) => onNameChange(event.target.value)} autoFocus />
        </label>
        <label>
          Product Idea
          <textarea value={idea} onChange={(event) => onIdeaChange(event.target.value)} rows={6} />
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" disabled={!name.trim() || !idea.trim()}>Create Project</button>
        </div>
      </form>
    </ModalFrame>
  );
}

export function EditProjectModal({ project, name, idea, onNameChange, onIdeaChange, onSubmit, onClose }) {
  return (
    <ModalFrame
      title="Edit Project"
      subtitle="These fields shape the library card only. Published Layer 0 brief content is unchanged."
      onClose={onClose}
      className="compact-modal"
    >
      <form className="modal-form" onSubmit={onSubmit}>
        <label>
          Name
          <input value={name} onChange={(event) => onNameChange(event.target.value)} autoFocus />
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
      title="Import Project Archive"
      subtitle="Import creates a new project ID and keeps the source archive intact."
      onClose={onClose}
      className="compact-modal"
    >
      <form className="modal-form" onSubmit={onSubmit}>
        <div className="import-schema-note">
          <strong>Expected archive</strong>
          <span>Use a Strata project archive zip containing manifest.json, project.json, and tables/*.json. Import creates a separate project and keeps the archive unchanged.</span>
        </div>
        <label>
          Archive path
          <input value={archivePath} onChange={(event) => onArchivePathChange(event.target.value)} placeholder="C:\\path\\to\\project-archive.zip" autoFocus />
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" disabled={!archivePath.trim()}>Import</button>
        </div>
      </form>
    </ModalFrame>
  );
}

export function GuideModal({ onClose }) {
  // Shows app workflow guidance without leaving the current project context.
  return (
    <ModalFrame
      title="Guide"
      subtitle="Use this as a quick map when you need to decide what to do next, not as a full reference manual."
      onClose={onClose}
      className="guide-modal"
    >
      <div className="guide-stack">
        {GUIDE_SECTIONS.map((group) => (
          <div key={group.heading} className="guide-group">
            <h3>{group.heading}</h3>
            <div className="guide-grid">
              {group.sections.map((section) => (
                <div key={section.title} className="guide-card">
                  <strong>{section.title}</strong>
                  <p className="muted">{section.body}</p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </ModalFrame>
  );
}
