import { layer1Pillars, layer2FeaturesByPillar, statusLabel } from "./workspaceSelectors";
import WorkspacePageLayout, { WorkspaceStatusBadge } from "./WorkspacePage";

function chipClass(status) {
  if (["kept", "prioritized", "approved"].includes(status)) return "kept";
  if (["cut", "disliked", "rejected"].includes(status)) return "cut";
  if (status === "merged") return "merged";
  return "pending";
}

export default function MapView({ snapshot, layerStatus, onNavigate }) {
  const pillars = layer1Pillars(snapshot);
  const featuresByPillar = layer2FeaturesByPillar(snapshot);
  const rows = [
    {
      key: "layer0",
      title: "Product Idea",
      body: snapshot?.brief?.product_idea || snapshot?.project?.idea || "Start with the product plan.",
      chips: snapshot?.brief ? [{ id: "layer0-root", label: "Product brief", status: snapshot.brief.status, tab: "layer0" }] : [],
    },
    {
      key: "layer1",
      title: "Pillars",
      body: "Pillars approved or rejected from the product brief.",
      chips: pillars.map((pillar) => ({ id: pillar.id, label: pillar.title, status: pillar.status, tab: "layer1" })),
    },
    {
      key: "layer2",
      title: "Features",
      body: "Feature candidates grouped below their Layer 1 owner.",
      chips: [...featuresByPillar.values()].flat().map((feature) => ({
        id: feature.id,
        label: feature.canonical_name,
        status: feature.status,
        tab: "layer2",
      })),
    },
  ];

  return (
    <WorkspacePageLayout
      id="workspace-panel-map"
      ariaLabel="Project map"
      className="workspace-map"
      title="Map"
      description="Review the product idea, pillars, and features in one overview."
      status="draft"
    >
      {rows.map((row) => {
        const state = layerStatus[row.key] || { status: "locked", label: "Locked" };
        return (
          <article key={row.key} className={`workspace-map-row ${state.status}`}>
            <div className="workspace-map-rail" aria-hidden="true">
              <span />
            </div>
            <div className="workspace-map-copy">
              <div className="workspace-map-row-head">
                <div>
                  <h3>{row.title}</h3>
                  <p className="muted">{row.body}</p>
                </div>
                <WorkspaceStatusBadge status={state.status}>{state.label || statusLabel(state.status)}</WorkspaceStatusBadge>
              </div>
              {row.chips.length ? (
                <div className="workspace-chip-row">
                  {row.chips.map((chip) => (
                    <button
                      key={chip.id}
                      type="button"
                      className={`workspace-chip ${chipClass(chip.status)}`}
                      onClick={() => onNavigate(chip.tab, chip.id)}
                      title={`Open ${chip.label}`}
                    >
                      {chip.label}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="muted">No items yet.</p>
              )}
            </div>
          </article>
        );
      })}
    </WorkspacePageLayout>
  );
}
