import { useEffect, useRef } from "react";
import { LAYER_TABS, statusLabel } from "./workspaceSelectors";

function tabStatusText(tab, state, locked) {
  if (locked) return "Locked";
  if (state.status === "needs_review") return "Needs review";
  if (state.label === "Published") return "Published";
  if (state.status === "complete") return "Complete";
  if (state.label === "Feature expansions ready" || state.label === "Layer 3 ready") return "Approved";
  if (state.label === "Draft") return "Draft";
  if (tab.id === "map") return "Overview";
  if (state.label?.toLowerCase().includes("review") || state.label?.toLowerCase().includes("generate") || state.label?.toLowerCase().includes("approve")) {
    return "Needs review";
  }
  return statusLabel(state.status);
}

function isCompleteState(state) {
  return ["complete", "approved", "published"].includes(state.status) || ["Published", "Reviewed", "Approved", "Layer 3 ready"].includes(state.label);
}

export default function LayerTabBar({ activeTab, layerStatus, onTabChange }) {
  const activeTabRef = useRef(null);

  useEffect(() => {
    // Keeps the selected workflow step visible when compact navigation scrolls horizontally.
    if (window.matchMedia("(max-width: 860px)").matches) {
      activeTabRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
    }
  }, [activeTab]);

  return (
    <div className="workspace-layer-tabs" role="tablist" aria-label="Project workflow">
      {LAYER_TABS.map((tab) => {
        const state = layerStatus[tab.statusKey] || { status: "locked", locked: true, label: "Locked" };
        const locked = Boolean(state.locked);
        const disabledTitle = state.label;
        const statusText = tabStatusText(tab, state, locked);
        const complete = isCompleteState(state);
        const needsReview = statusText === "Needs review";
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`workspace-panel-${tab.id}`}
            ref={activeTab === tab.id ? activeTabRef : null}
            className={activeTab === tab.id ? `workspace-layer-tab selected ${state.status}` : `workspace-layer-tab ${state.status}`}
            disabled={locked}
            title={locked ? disabledTitle : `${tab.label}: ${state.label}`}
            onClick={() => onTabChange(tab.id)}
          >
            <span className="workspace-tab-topline">
              {tab.badge ? <span className="workspace-layer-badge">{tab.badge}</span> : null}
              {complete ? <span aria-hidden="true" className="workspace-complete-mark">OK</span> : null}
              {needsReview ? <span aria-hidden="true" className="workspace-review-mark">!</span> : null}
              {locked ? <span aria-hidden="true" className="workspace-lock">L</span> : null}
            </span>
            <strong>{tab.label}</strong>
            <small className={`workspace-tab-status ${statusText.toLowerCase().replaceAll(" ", "-")}`}>{statusText}</small>
          </button>
        );
      })}
    </div>
  );
}
