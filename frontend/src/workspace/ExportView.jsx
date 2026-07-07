import WorkspacePageLayout, { WorkspaceActionButton, WorkspaceActionGroup } from "./WorkspacePage";

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
      primaryAction={<WorkspaceActionButton primary onClick={onExport}>Export</WorkspaceActionButton>}
      actions={(
        <>
          <WorkspaceActionGroup label="Export">
            <WorkspaceActionButton secondary onClick={onExport}>Export full project</WorkspaceActionButton>
            <WorkspaceActionButton secondary onClick={onLayer2Export}>Export Layer 2</WorkspaceActionButton>
            {onLayer3Export ? <WorkspaceActionButton secondary onClick={onLayer3Export}>Export Layer 3</WorkspaceActionButton> : null}
            <WorkspaceActionButton secondary onClick={onProjectArchiveExport}>Export archive</WorkspaceActionButton>
          </WorkspaceActionGroup>
        </>
      )}
    >
      <div className="project-tool-section">
        <div className="project-tool-section-header">
          {exportCount ? <span className="project-tool-inline-meta">{exportCount} saved path{exportCount === 1 ? "" : "s"}</span> : <span className="project-tool-inline-meta">No saved exports yet</span>}
        </div>
        <p className="muted">Exports are written to the configured local exports folder.</p>
        {lastExport ? (
          <div className="export-result" role="status">
            <strong>{lastExport.kind} export created</strong>
            {lastExport.markdown_path ? <span>Markdown: {lastExport.markdown_path}</span> : null}
            <span>JSON: {lastExport.json_path}</span>
          </div>
        ) : (
          <div className="panel guided-empty-state">
            <strong>No exports created yet.</strong>
            <p className="muted">Use one of the export actions above after you finish the Layer 2 review pass.</p>
          </div>
        )}
        {layer2Graph?.review_open ? (
          <p className="warning">Layer 2 export includes unresolved review state. Downstream handoff still requires approved features.</p>
        ) : null}
      </div>
    </WorkspacePageLayout>
  );
}
