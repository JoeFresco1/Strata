import { useEffect, useState } from "react";
import { splitLines } from "./layer2WorkbenchUtils";

export default function CompetitiveIntelligencePanel({ graph, pillars, onCompetitiveSettings }) {
  const rows = graph?.workbench?.rows || [];
  const settings = graph?.competitive_settings || { known_competitors: [], research_mode: "known_only" };
  const [competitorsText, setCompetitorsText] = useState((settings.known_competitors || []).join("\n"));
  const [researchMode, setResearchMode] = useState(settings.research_mode || "known_only");
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
            <h3>Competitive Intelligence</h3>
            <p className="muted">Manual feature evidence now; automated expansion can use these known competitors later.</p>
          </div>
          <button type="button" onClick={saveSettings} disabled={!onCompetitiveSettings}>Save Competitors</button>
        </div>
        <div className="brief-grid">
          <label>
            Known Competitors
            <textarea value={competitorsText} onChange={(event) => setCompetitorsText(event.target.value)} rows={6} />
          </label>
          <label>
            Research Mode
            <select value={researchMode} onChange={(event) => setResearchMode(event.target.value)}>
              <option value="known_only">Focus on known competitors only</option>
              <option value="expand_from_known">Expand from known competitors later</option>
            </select>
          </label>
        </div>
      </div>
      <div className="panel layer2-graph-panel">
        <h3>Layer 2 Competitor Matrix</h3>
        <div className="layer2-table-wrap">
          <table className="layer2-feature-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Pillar</th>
                {competitors.map((competitor) => <th key={competitor}>{competitor}</th>)}
                <th>Coverage %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td><strong>{row.canonical_name}</strong></td>
                  <td>{pillarById[row.owner_pillar_id]?.title || "Unassigned"}</td>
                  {competitors.map((competitor) => {
                    const match = (row.evidence || []).find((item) => item.competitor_name.toLowerCase() === competitor.toLowerCase());
                    return <td key={`${row.id}-${competitor}`}>{match?.coverage_status || "unclear"}</td>;
                  })}
                  <td>{row.competitor_coverage_score || 0}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!competitors.length ? <p className="muted">Add known competitors to start a manual matrix.</p> : null}
      </div>
    </section>
  );
}
