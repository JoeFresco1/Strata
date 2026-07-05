import { useEffect, useState } from "react";
import { splitLines } from "./layer2WorkbenchUtils";

function competitorLabel(value) {
  // Match URL-style competitor seeds to the normalized names stored on evidence rows.
  const trimmed = value.trim();
  const looksLikeUrl = trimmed.includes("://") || (!trimmed.includes(" ") && trimmed.includes("."));
  if (!looksLikeUrl) return trimmed;
  try {
    const url = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
    return url.hostname.replace(/^www\./, "").split(".")[0].replace(/^./, (character) => character.toUpperCase());
  } catch {
    return trimmed;
  }
}

function latestEvidence(evidence, competitor) {
  // Evidence arrives newest-first, so the first normalized competitor match is the current matrix value.
  const label = competitorLabel(competitor).toLowerCase();
  return (evidence || []).find((item) => item.competitor_name.toLowerCase() === label);
}

export default function CompetitiveIntelligencePanel({ graph, pillars, onCompetitiveSettings, onResearch, researchJobs = [] }) {
  const rows = graph?.workbench?.rows || [];
  const settings = graph?.competitive_settings || { known_competitors: [], research_mode: "known_only" };
  const [competitorsText, setCompetitorsText] = useState((settings.known_competitors || []).join("\n"));
  const [researchMode, setResearchMode] = useState(settings.research_mode || "known_only");
  const [selectedCell, setSelectedCell] = useState(null);
  const competitors = splitLines(competitorsText);
  const pillarById = Object.fromEntries(pillars.map((pillar) => [pillar.id, pillar]));

  useEffect(() => {
    setCompetitorsText((settings.known_competitors || []).join("\n"));
    setResearchMode(settings.research_mode || "known_only");
  }, [settings.project_id, settings.research_mode, JSON.stringify(settings.known_competitors || [])]);

  async function saveSettings() {
    if (!onCompetitiveSettings) return;
    await onCompetitiveSettings({ known_competitors: competitors, research_mode: researchMode });
  }

  return (
    <section className="tab-content">
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>Competitive intelligence</h3>
            <p className="muted">Run cited local research across the active Layer 2 feature set.</p>
          </div>
          <div className="button-row">
            <button type="button" onClick={saveSettings} disabled={!onCompetitiveSettings}>Save competitors</button>
            <button type="button" className="secondary-button" onClick={() => onResearch?.([])} disabled={!onResearch}>Research all</button>
          </div>
        </div>
        <div className="brief-grid">
          <label>
            Known competitors
            <textarea value={competitorsText} onChange={(event) => setCompetitorsText(event.target.value)} rows={6} />
            <span className="muted">Layer 0 competitors are inherited here; add Layer 2-specific competitors as needed.</span>
          </label>
          <label>
            Research mode
            <select value={researchMode} onChange={(event) => setResearchMode(event.target.value)}>
              <option value="known_only">Focus on known competitors only</option>
              <option value="expand_from_known">Discover adjacent competitors during research</option>
            </select>
          </label>
        </div>
      </div>
      <div className="panel layer2-graph-panel">
        <h3>Layer 2 competitor matrix</h3>
        {!rows.length ? (
          <div className="guided-empty-state">
            <strong>No Layer 2 feature rows yet.</strong>
            <p className="muted">Generate or add Layer 2 features first, then run competitor research to populate the matrix.</p>
          </div>
        ) : !competitors.length ? (
          <div className="guided-empty-state">
            <strong>No competitors selected.</strong>
            <p className="muted">Add competitors above or inherit them from Layer 0 before running the matrix.</p>
          </div>
        ) : (
          <div className="layer2-table-wrap">
            <table className="layer2-feature-table">
              <thead>
                <tr>
                  <th scope="col">Feature</th>
                  <th scope="col">Pillar</th>
                  {competitors.map((competitor) => <th key={competitor} scope="col">{competitorLabel(competitor)}</th>)}
                  <th scope="col">Coverage %</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td><strong>{row.canonical_name}</strong></td>
                    <td>{pillarById[row.owner_pillar_id]?.title || "Unassigned"}</td>
                    {competitors.map((competitor) => {
                      const match = latestEvidence(row.evidence, competitor);
                      return (
                        <td key={`${row.id}-${competitor}`}>
                          <button type="button" className="matrix-cell-button" onClick={() => setSelectedCell({ row, competitor, match })}>
                            {match?.coverage_status || "unclear"}
                          </button>
                        </td>
                      );
                    })}
                    <td>{row.competitor_coverage_score || 0}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {selectedCell ? (
          <div className="layer2-evidence-history">
            <div className="panel-header">
              <h4>{selectedCell.row.canonical_name} | {competitorLabel(selectedCell.competitor)}</h4>
              <button type="button" className="secondary-button" onClick={() => setSelectedCell(null)}>Close</button>
            </div>
            {(selectedCell.row.evidence || [])
              .filter((item) => item.competitor_name.toLowerCase() === competitorLabel(selectedCell.competitor).toLowerCase())
              .map((item) => (
                <div key={item.id} className="evidence-history-item">
                  <strong>{item.coverage_status} | {item.confidence}% | {item.source_type}</strong>
                  {item.rationale ? <p>{item.rationale}</p> : null}
                  {item.evidence_snippet ? <p className="muted">{item.evidence_snippet}</p> : null}
                  {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">Open source</a> : null}
                </div>
              ))}
            {!selectedCell.match ? <p className="muted">No evidence has been recorded for this cell.</p> : null}
          </div>
        ) : null}
      </div>
      {(researchJobs || []).filter((job) => job.scope === "layer2").slice(0, 1).map((job) => (
        <div key={job.id} className={`panel status-card ${job.status}`}>
          <strong>Latest Layer 2 research: {job.status} | {job.progress}%</strong>
          {(job.details?.warnings || []).map((warning) => <span key={warning} className="warning-text">{warning}</span>)}
        </div>
      ))}
    </section>
  );
}
