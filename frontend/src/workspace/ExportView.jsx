import { useState } from "react";
import WorkspacePageLayout, { WorkspaceActionButton } from "./WorkspacePage";

export default function ExportView({
  layer2Graph,
  lastExport,
  onExport,
  onLayer2Export,
  onLayer3Export,
  onProjectArchiveExport,
}) {
  const [mode, setMode] = useState("approved");
  const exportCount = [lastExport?.markdown_path, lastExport?.json_path].filter(Boolean).length;
  const manifest = lastExport?.manifest;
  const issues = lastExport?.issues || [];

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
          <label className="workspace-filter-field">
            <span>Compilation mode</span>
            <select value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="approved">Approved</option>
              <option value="draft">Draft</option>
              <option value="diagnostic">Diagnostic</option>
            </select>
          </label>
          <WorkspaceActionButton primary onClick={() => onExport(mode)}>Compile and export</WorkspaceActionButton>
          <span className="workspace-action-divider" aria-hidden="true" />
          <span className="workspace-card-label">Diagnostics and archive</span>
          <div className="button-row">
            <WorkspaceActionButton secondary onClick={onLayer2Export}>Layer 2 diagnostic</WorkspaceActionButton>
            {onLayer3Export ? <WorkspaceActionButton secondary onClick={onLayer3Export}>Layer 3 diagnostic</WorkspaceActionButton> : null}
            <WorkspaceActionButton secondary onClick={onProjectArchiveExport}>Export archive</WorkspaceActionButton>
          </div>
        </div>
      )}
    >
      <section className="export-history">
        {lastExport ? (
          <div className="export-result" role="status">
            <strong>{lastExport.kind} {exportCount ? "export created" : "manifest compiled"}</strong>
            {manifest ? <span>Manifest v{manifest.sequence_number} · {manifest.mode} · {new Date(manifest.created_at).toLocaleString()}</span> : null}
            {manifest ? <span>Status: {manifest.exportable ? "exportable" : manifest.status}</span> : null}
            {lastExport.markdown_path ? <span>Markdown: {lastExport.markdown_path}</span> : null}
            {lastExport.json_path ? <span>JSON: {lastExport.json_path}</span> : null}
            {lastExport.markdown_download_url || lastExport.json_download_url ? (
              <div className="button-row">
                {lastExport.markdown_download_url ? <a className="download-link-button" href={lastExport.markdown_download_url}>Download Markdown</a> : null}
                {lastExport.json_download_url ? <a className="download-link-button" href={lastExport.json_download_url}>Download JSON</a> : null}
              </div>
            ) : null}
            {issues.length ? (
              <details>
                <summary>{issues.length} validation issue{issues.length === 1 ? "" : "s"}</summary>
                <ul>{issues.map((issue, index) => <li key={`${issue.code}-${index}`}><code>{issue.code}</code>: {issue.message}</li>)}</ul>
              </details>
            ) : null}
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
