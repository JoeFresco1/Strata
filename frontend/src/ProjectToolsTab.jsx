import { CompetitiveIntelligencePanel } from "./Layer2GraphPanel";
import { ProjectSettingsTab } from "./ModelSettingsPanel";
import { approvedNodes } from "./appUtils";

export default function ProjectToolsTab({
  config,
  competitiveIntelligenceEnabled,
  layer2Graph,
  lastExport,
  memories,
  nodes,
  projectModelSettings,
  projectSettingsSaveState,
  quarantine,
  researchJobs,
  onCompetitiveSettings,
  onExport,
  onLayer2Export,
  onProjectSettingsChange,
  onProjectSettingsSave,
  onResearchLayer2,
  onProjectArchiveExport,
}) {
  return (
    <section className="tab-content">
      <details className="panel project-tool-section" open>
        <summary>Project settings</summary>
        <ProjectSettingsTab
          settings={projectModelSettings}
          config={config}
          saveState={projectSettingsSaveState}
          onChange={onProjectSettingsChange}
          onSave={onProjectSettingsSave}
        />
      </details>
      <details className="panel project-tool-section">
        <summary>Export</summary>
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
        ) : null}
        {layer2Graph.review_open ? (
          <p className="warning">Layer 2 export includes unresolved review state. Layer 3 still requires approved features.</p>
        ) : null}
      </details>
      {competitiveIntelligenceEnabled ? (
        <details className="panel project-tool-section">
          <summary>Competitive intelligence</summary>
          <CompetitiveIntelligencePanel
            graph={layer2Graph}
            pillars={approvedNodes(nodes, "pillar")}
            onCompetitiveSettings={onCompetitiveSettings}
            onResearch={onResearchLayer2}
            researchJobs={researchJobs}
          />
        </details>
      ) : null}
      <details className="panel export-diagnostics">
        <summary>Advanced diagnostics and generation memory</summary>
        <p className="muted">{memories.length} memory records{quarantine ? " including Layer 1 quarantine data" : ""}.</p>
        <details>
          <summary>Generation memory</summary>
          <pre>{JSON.stringify(memories, null, 2)}</pre>
        </details>
        {quarantine ? (
          <details>
            <summary>Layer 1 quarantine</summary>
            <pre>{JSON.stringify(quarantine.content, null, 2)}</pre>
          </details>
        ) : null}
      </details>
    </section>
  );
}
