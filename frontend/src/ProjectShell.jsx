import "./ProjectShell.css";
const GUIDE_SECTIONS = [
  {
    title: "How Strata flows",
    body: "Create a project, shape the Layer 0 brief in Plan or Form mode, publish it, then expand into Layers 1 through 3 with research and review along the way.",
  },
  {
    title: "What app defaults do",
    body: "App Settings define the reusable model profiles and default assignments that seed new projects. Existing projects keep their own overrides unless you edit them directly.",
  },
  {
    title: "What project overrides do",
    body: "Each project can override the global defaults for planning, generation, research, and embeddings without changing the rest of the library.",
  },
];

// Formats project timestamps consistently inside the project library.
function formatProjectCardDate(value) {
  return new Date(value).toLocaleString();
}

export function ProjectHub({
  projects,
  sortOrder,
  onSortOrderChange,
  onOpenProject,
  onCreateProject,
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
          <button type="button" onClick={onCreateProject}>Create New Project</button>
          <label className="compact-select">
            Sort
            <select value={sortOrder} onChange={(event) => onSortOrderChange(event.target.value)}>
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
            </select>
          </label>
        </div>
      </div>
      {projects.length ? (
        <div className="project-grid">
          {projects.map((project) => (
            <button key={project.id} type="button" className="project-card" onClick={() => onOpenProject(project.id)}>
              <div className="project-card-head">
                <strong>{project.name}</strong>
                <span className={`status-pill ${project.brief_status || "draft"}`}>{project.brief_status || "draft"}</span>
              </div>
              <p>{project.idea}</p>
              <div className="project-card-meta">
                <span>Created {formatProjectCardDate(project.created_at)}</span>
                <span>{project.node_count || 0} nodes</span>
                <span>{project.pillar_count || 0} pillars</span>
              </div>
            </button>
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

