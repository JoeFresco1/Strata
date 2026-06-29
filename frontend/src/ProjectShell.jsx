import "./ProjectShell.css";
const GUIDE_SECTIONS = [
  {
    title: "How Strata flows",
    body: "Create a project, shape the Layer 0 brief in Plan or Form mode, publish it, then expand into Layers 1 through 3 with research and review along the way.",
  },
  {
    title: "What app defaults do",
    body: "App Settings define the reusable execution strategy, model profiles, and default assignments that seed new projects. Existing projects keep their own overrides unless you edit them directly.",
  },
  {
    title: "What project overrides do",
    body: "Each project can override the global execution strategy for planning, generation, research, assistant work, and embeddings without changing the rest of the library.",
  },
];

// Formats project timestamps consistently inside the project library.
function formatProjectCardDate(value) {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
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
  // ProjectHub is the landing workspace for opening or creating Strata projects.
  return (
    <section className="project-hub">
      <div className="hub-header">
        <div>
          <h1>Project Library</h1>
          <p className="muted">Open a project to keep building, or create a new one and jump straight into Layer 0.</p>
        </div>
        <div className="hub-actions">
          <input className="project-search" value={searchQuery} onChange={(event) => onSearchQueryChange(event.target.value)} placeholder="Search projects" />
          <div className="segmented-control">
            {["active", "archived", "all"].map((state) => (
              <button key={state} type="button" className={lifecycleState === state ? "active" : ""} onClick={() => onLifecycleStateChange(state)}>{state}</button>
            ))}
          </div>
          <button type="button" onClick={onCreateProject}>Create New Project</button>
          <button type="button" className="secondary-button" onClick={onImportProject}>Import Project Archive</button>
          <label className="compact-select">
            Sort
            <select value={sortOrder} onChange={(event) => onSortOrderChange(event.target.value)}>
              <option value="updated">Updated</option>
              <option value="last_opened">Last Opened</option>
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
              <option value="name">Name</option>
            </select>
          </label>
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
                <strong>{project.name}</strong>
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
                <button type="button" className="secondary-button" onClick={() => onEditProject(project)}>Edit</button>
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
          <p className="muted">No projects yet. Use the Create New Project button to start the first brief.</p>
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
      subtitle="A quick explanation of how the app fits together."
      onClose={onClose}
      className="compact-modal"
    >
      <div className="guide-stack">
        {GUIDE_SECTIONS.map((section) => (
          <div key={section.title} className="guide-card">
            <strong>{section.title}</strong>
            <p className="muted">{section.body}</p>
          </div>
        ))}
      </div>
    </ModalFrame>
  );
}

