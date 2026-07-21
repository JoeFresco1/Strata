import WorkspacePageLayout, { WorkspaceActionButton } from "./WorkspacePage";

export default function ExportView({
  layer2Graph,
  lastExport,
  onExport,
  onLayer2Export,
  onLayer3Export,
  onProjectArchiveExport,
}) {
  const exportCount = [lastExport?.markdown_path, lastExport?.json_path].filter(Boolean).length;

  return (
    <WorkspacePageLayout
      id="workspace-panel-export"
      ariaLabel="Project exports"
      title="Export"
      description="Create handoff files and archives once the reviewed product structure is ready to share."
      status={lastExport ? "published" : layer2Graph?.review_open ? "needs_review" : "draft"}
      primaryAction={null}
      actions={(
        <div className="export-secondary-actions">
          <WorkspaceActionButton primary onClick={onExport}>Export full project</WorkspaceActionButton>
          <span className="workspace-action-divider" aria-hidden="true" />
          <span className="workspace-card-label">Other formats</span>
          <div className="button-row">
            <WorkspaceActionButton secondary onClick={onLayer2Export}>Export Layer 2</WorkspaceActionButton>
            {onLayer3Export ? <WorkspaceActionButton secondary onClick={onLayer3Export}>Export Layer 3</WorkspaceActionButton> : null}
            <WorkspaceActionButton secondary onClick={onProjectArchiveExport}>Export archive</WorkspaceActionButton>
          </div>
        </div>
      )}
    >
      <section className="export-history">
        {lastExport ? (
          <div className="export-result" role="status">
            <strong>{lastExport.kind} export created</strong>
            {lastExport.markdown_path ? <span>Markdown: {lastExport.markdown_path}</span> : null}
            <span>JSON: {lastExport.json_path}</span>
          </div>
        ) : (
          <p className="muted">No exports yet. Your handoff files will appear here after you export the full project or a focused layer.</p>
        )}
        {layer2Graph?.review_open ? (
          <p className="warning">Layer 2 export includes unresolved review state. Downstream handoff still requires approved features.</p>
        ) : null}
      </section>
    </WorkspacePageLayout>
  );
}
