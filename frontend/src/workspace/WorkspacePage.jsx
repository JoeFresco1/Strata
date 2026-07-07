const STATUS_LABELS = {
  active: "Draft",
  approved: "Approved",
  candidate: "Generated",
  complete: "Approved",
  cut: "Rejected",
  draft: "Draft",
  exclude: "Rejected",
  generated: "Generated",
  include: "Kept",
  kept: "Kept",
  locked: "Needs review",
  merged: "Kept",
  needs_review: "Needs review",
  not_generated: "Draft",
  prioritized: "Kept",
  published: "Published",
  rejected: "Rejected",
  reviewed: "Approved",
  running: "Generated",
  undecided: "Needs review",
};

export function displayStatusLabel(status) {
  const key = String(status || "draft").toLowerCase();
  return STATUS_LABELS[key] || key.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

export function displayStatusClass(status) {
  const label = displayStatusLabel(status).toLowerCase().replaceAll(" ", "-");
  return `workspace-status-${label}`;
}

export function WorkspaceStatusBadge({ status, children }) {
  return (
    <span className={`status-pill workspace-status-badge ${displayStatusClass(status)}`}>
      {children || displayStatusLabel(status)}
    </span>
  );
}

export function WorkspaceActionButton({
  children,
  className = "",
  disabled = false,
  disabledReason = "",
  destructive = false,
  primary = false,
  secondary = false,
  title = "",
  ...props
}) {
  const classes = [
    primary ? "" : "secondary-button",
    secondary ? "secondary-button" : "",
    destructive ? "danger-button" : "",
    className,
  ].filter(Boolean).join(" ");
  const resolvedTitle = disabled && disabledReason ? disabledReason : title;
  return (
    <span className="workspace-action-wrapper">
      <button
        type="button"
        className={classes || undefined}
        disabled={disabled}
        title={resolvedTitle || undefined}
        {...props}
      >
        {children}
      </button>
      {disabled && disabledReason ? <small className="workspace-disabled-reason">{disabledReason}</small> : null}
    </span>
  );
}

export function WorkspacePageHeader({ title, description, status, primaryAction }) {
  return (
    <header className="workspace-page-header panel">
      <div>
        <h3>{title}</h3>
        <p className="muted">{description}</p>
      </div>
      <div className="workspace-page-header-side">
        <WorkspaceStatusBadge status={status} />
        {primaryAction}
      </div>
    </header>
  );
}

export function WorkspaceActionGroup({ label, children }) {
  if (!children) return null;
  return (
    <div className="workspace-action-group">
      <strong>{label}</strong>
      <div className="button-row">{children}</div>
    </div>
  );
}

export function WorkspaceActionBar({ children, label = "Actions" }) {
  if (!children) return null;
  return (
    <section className="workspace-action-card panel" aria-label={label}>
      <span className="workspace-card-label">{label}</span>
      <div className="workspace-action-grid">{children}</div>
    </section>
  );
}

export function WorkspaceFilterBar({ children }) {
  if (!children) return null;
  return (
    <section className="workspace-filter-card panel" aria-label="Filter and search">
      {children}
    </section>
  );
}

export function WorkspaceMain({ children }) {
  return <section className="workspace-main-card">{children}</section>;
}

export default function WorkspacePageLayout({
  id,
  ariaLabel,
  className = "",
  title,
  description,
  status,
  primaryAction,
  actions,
  filters,
  children,
  details,
}) {
  return (
    <section className={`workspace-layer-panel workspace-page ${className}`.trim()} id={id} role="tabpanel" aria-label={ariaLabel}>
      <WorkspacePageHeader title={title} description={description} status={status} primaryAction={primaryAction} />
      <WorkspaceActionBar>{actions}</WorkspaceActionBar>
      <WorkspaceFilterBar>{filters}</WorkspaceFilterBar>
      <WorkspaceMain>{children}</WorkspaceMain>
      {details ? <section className="workspace-detail-card">{details}</section> : null}
    </section>
  );
}
