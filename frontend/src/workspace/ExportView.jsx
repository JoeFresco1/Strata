export default function ExportView({
  layer2Graph,
  lastExport,
  onExport,
  onLayer2Export,
  onProjectArchiveExport,
}) {
  const exportCount = [lastExport?.markdown_path, lastExport?.json_path].filter(Boolean).length;

  return (
    <section className="workspace-layer-panel" id="workspace-panel-export" role="tabpanel" aria-label="Project exports">
      <div className="panel project-tool-section">
        <div className="project-tool-section-header">
          <div>
            <h3>Exports and handoff</h3>
            <p className="muted">Create portable outputs once Layer 3 is approved and the project is ready to hand off.</p>
          </div>
          {exportCount ? <span className="project-tool-inline-meta">{exportCount} saved path{exportCount === 1 ? "" : "s"}</span> : null}
        </div>
        <div className="button-row">
          <button type="button" onClick={onExport}>
            Create Full Project Export
          </button>
          <button type="button" onClick={onLayer2Export}>
            Create Layer 2 Export
          </button>
          <button type="button" onClick={onProjectArchiveExport}>
            Export Project Archive
          </button>
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
            <p className="muted">Use one of the export actions above after you finish the Layer 3 review pass.</p>
          </div>
        )}
        {layer2Graph?.review_open ? (
          <p className="warning">Layer 2 export includes unresolved review state. Downstream handoff still requires approved features.</p>
        ) : null}
      </div>
    </section>
  );
}
