import { LAYER_TABS, statusLabel } from "./workspaceSelectors";

export default function LayerTabBar({ activeTab, layerStatus, onTabChange }) {
  return (
    <div className="workspace-layer-tabs" role="tablist" aria-label="Workspace layers">
      {LAYER_TABS.map((tab) => {
        const state = layerStatus[tab.statusKey] || { status: "locked", locked: true, label: "Locked" };
        const locked = Boolean(state.locked);
        const disabledTitle = state.label;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`workspace-panel-${tab.id}`}
            className={activeTab === tab.id ? `workspace-layer-tab selected ${state.status}` : `workspace-layer-tab ${state.status}`}
            disabled={locked}
            title={locked ? disabledTitle : `${tab.label}: ${state.label}`}
            onClick={() => onTabChange(tab.id)}
          >
            {locked ? <span aria-hidden="true" className="workspace-lock">L</span> : null}
            <strong>{tab.label}</strong>
            <small>{locked ? "Locked" : statusLabel(state.status)}</small>
          </button>
        );
      })}
    </div>
  );
}
