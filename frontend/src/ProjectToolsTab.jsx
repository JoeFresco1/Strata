import { CompetitiveIntelligencePanel } from "./Layer2GraphPanel";
import { ProjectSettingsTab } from "./ModelSettingsPanel";
import { approvedNodes } from "./appUtils";

function computeModeLabel(value) {
  return {
    local_first: "Local-first",
    api_first: "API-first",
    blended: "Blended",
  }[value] || "Local-first";
}

function routingLabel(value) {
  return value === "api" ? "Cloud/API" : "Local";
}

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
  const settings = projectModelSettings || {};
  const routingPolicy = settings.routing_policy || {};
  const exportCount = [lastExport?.markdown_path, lastExport?.json_path].filter(Boolean).length;

  return (
    <section className="tab-content">
      <div className="panel project-settings-summary-card">
        <div className="panel-header">
          <div>
            <h3>Project behavior</h3>
            <p className="muted">Confirm how this project will run before you change anything deeper.</p>
          </div>
          <span className={`status-pill ${projectSettingsSaveState === "saved" ? "published" : "draft"}`}>
            {projectSettingsSaveState === "saving"
              ? "Saving"
              : projectSettingsSaveState === "saved"
                ? "Saved"
                : "Ready"}
          </span>
        </div>
        <div className="project-settings-summary-grid">
          <div className="project-settings-summary-item">
            <span>Compute mode</span>
            <strong>{computeModeLabel(settings.execution_intent)}</strong>
          </div>
          <div className="project-settings-summary-item">
            <span>Layer 0</span>
            <strong>{routingLabel(routingPolicy.layer0)}</strong>
          </div>
          <div className="project-settings-summary-item">
            <span>Generation</span>
            <strong>{routingLabel(routingPolicy.generation)}</strong>
          </div>
          <div className="project-settings-summary-item">
            <span>Research</span>
            <strong>{routingLabel(routingPolicy.research)}</strong>
          </div>
          <div className="project-settings-summary-item">
            <span>Assistant</span>
            <strong>{routingLabel(routingPolicy.assistant)}</strong>
          </div>
          <div className="project-settings-summary-item">
            <span>Competitive intel</span>
            <strong>{competitiveIntelligenceEnabled ? "On" : "Off"}</strong>
          </div>
        </div>
      </div>

      <div className="panel project-tool-section">
        <div className="project-tool-section-header">
          <div>
            <h3>Project settings</h3>
            <p className="muted">Decide how this one project should run without changing global defaults.</p>
          </div>
        </div>
        <ProjectSettingsTab
          settings={projectModelSettings}
          config={config}
          saveState={projectSettingsSaveState}
          onChange={onProjectSettingsChange}
          onSave={onProjectSettingsSave}
        />
      </div>

      <div className="panel project-tool-section">
        <div className="project-tool-section-header">
          <div>
            <h3>Exports and handoff</h3>
            <p className="muted">Create portable outputs once the project state is where you want it.</p>
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
        ) : null}
        {layer2Graph.review_open ? (
          <p className="warning">Layer 2 export includes unresolved review state. Layer 3 still requires approved features.</p>
        ) : null}
      </div>

      {competitiveIntelligenceEnabled ? (
        <div className="panel project-tool-section">
          <div className="project-tool-section-header">
            <div>
              <h3>Competitive intelligence</h3>
              <p className="muted">Tune the competitor set and rerun feature-level evidence without leaving project controls.</p>
            </div>
          </div>
          <CompetitiveIntelligencePanel
            graph={layer2Graph}
            pillars={approvedNodes(nodes, "pillar")}
            onCompetitiveSettings={onCompetitiveSettings}
            onResearch={onResearchLayer2}
            researchJobs={researchJobs}
          />
        </div>
      ) : null}

      <details className="panel export-diagnostics">
        <summary>Diagnostics and generation memory</summary>
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
