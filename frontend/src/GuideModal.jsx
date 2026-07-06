import { useId, useState } from "react";
import { ModalFrame } from "./ProjectShell";
import {
  GUIDE_DECISION_ROUTES,
  GUIDE_FLOW_STEPS,
  GUIDE_OPERATIONAL_LAYERS,
  GUIDE_UTILITY_ROUTES,
} from "./guideContent";
import { useIsCompactWorkspace } from "./workspace/workspaceSelectors";

const GUIDE_TABS = [
  { id: "general", label: "General overview" },
  { id: "operational", label: "Operational overview" },
];

function GeneralGuideOverview() {
  return (
    <div className="guide-stack">
      <section className="panel guide-map-panel">
        <div className="guide-group-header">
          <span className="guide-eyebrow">Workflow map</span>
          <h3>Move from project context to a reviewed feature set.</h3>
        </div>
        <div className="guide-flow" aria-label="Strata workflow order">
          {GUIDE_FLOW_STEPS.map((step, index) => (
            <div key={step.label} className="guide-flow-item">
              <div className="guide-flow-node">
                <span className="guide-flow-index">{index + 1}</span>
                <span className="guide-flow-label">{step.label}</span>
              </div>
              <div className="guide-flow-copy">
                <strong>{step.title}</strong>
                <p className="muted">{step.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="panel guide-router">
        <div className="guide-group-header">
          <span className="guide-eyebrow">Decision router</span>
          <h3>Pick the row that matches what you are trying to do right now.</h3>
        </div>
        <div className="guide-route-list">
          {GUIDE_DECISION_ROUTES.map((route) => (
            <div key={route.need} className="guide-route-row">
              <strong>{route.need}</strong>
              <span className="guide-route-target">{route.go}</span>
              <p className="muted">{route.action}</p>
            </div>
          ))}
        </div>
      </section>
      <section className="panel guide-utilities">
        <div className="guide-group-header">
          <span className="guide-eyebrow">Utility surfaces</span>
          <h3>Use these when the product tree is not the thing that needs attention.</h3>
        </div>
        <div className="guide-utility-grid">
          {GUIDE_UTILITY_ROUTES.map((route) => (
            <div key={route.title} className="guide-utility-card">
              <strong>{route.title}</strong>
              <p className="muted">{route.body}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function OperationalGuideOverview() {
  const compact = useIsCompactWorkspace();

  return (
    <div className={`guide-operational ${compact ? "compact" : ""}`}>
      <section className="panel guide-operational-intro">
        <div className="guide-group-header">
          <span className="guide-eyebrow">Operational overview</span>
          <h3>See how work moves through the product layers before it becomes reviewed output.</h3>
        </div>
        <p className="muted">
          This is the canonical workflow model for Layers 0-3. It explains what the agent does, what you review,
          and what unlocks the next stage.
        </p>
      </section>

      <div className="guide-operational-list">
        {GUIDE_OPERATIONAL_LAYERS.map((layer) => (
          <section
            key={layer.id}
            className="panel guide-operational-layer"
            aria-label={`${layer.eyebrow} workflow`}
          >
            <div className="guide-group-header">
              <span className="guide-eyebrow">{layer.eyebrow}</span>
              <h3>{layer.title}</h3>
            </div>

            <div className="guide-operational-visual" aria-hidden="true">
              {layer.flow.map((step, index) => (
                <div key={step} className="guide-operational-step">
                  <div className="guide-operational-node">
                    <span className="guide-operational-index">{index + 1}</span>
                    <span>{step}</span>
                  </div>
                  {index < layer.flow.length - 1 ? <span className="guide-operational-connector">→</span> : null}
                </div>
              ))}
            </div>

            <div className={`guide-operational-details ${compact ? "compact" : ""}`}>
              <div className="guide-operational-detail">
                <strong>What it is</strong>
                <p className="muted">{layer.description}</p>
              </div>
              <div className="guide-operational-detail">
                <strong>Agent does</strong>
                <p className="muted">{layer.agentDoes}</p>
              </div>
              <div className="guide-operational-detail">
                <strong>You do</strong>
                <p className="muted">{layer.userDoes}</p>
              </div>
              <div className="guide-operational-detail">
                <strong>Gate / output</strong>
                <p className="muted">{layer.gateOutput}</p>
              </div>
            </div>
          </section>
        ))}
      </div>

      <section className="panel guide-operational-note">
        <strong>Supporting surfaces</strong>
        <p className="muted">
          Project Settings, App Settings, Runtime Analytics, Assistant, and exports support the workflow, but they are
          not separate core layers in the product sequence.
        </p>
      </section>
    </div>
  );
}

export default function GuideModal({ onClose }) {
  const [activeTab, setActiveTab] = useState("general");
  const tabListId = useId();
  const generalTabId = `${tabListId}-general-tab`;
  const operationalTabId = `${tabListId}-operational-tab`;
  const generalPanelId = `${tabListId}-general-panel`;
  const operationalPanelId = `${tabListId}-operational-panel`;

  return (
    <ModalFrame
      title="Guide"
      subtitle="A quick map for the current Strata workspace: orient, review, approve, and export."
      onClose={onClose}
      className="guide-modal"
    >
      <div className="guide-tab-shell">
        <div className="guide-tabs" role="tablist" aria-label="Guide sections">
          {GUIDE_TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            const tabId = tab.id === "general" ? generalTabId : operationalTabId;
            const panelId = tab.id === "general" ? generalPanelId : operationalPanelId;
            return (
              <button
                key={tab.id}
                id={tabId}
                type="button"
                role="tab"
                className={isActive ? "active" : ""}
                aria-selected={isActive}
                aria-controls={panelId}
                tabIndex={isActive ? 0 : -1}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        <div
          id={generalPanelId}
          role="tabpanel"
          aria-labelledby={generalTabId}
          hidden={activeTab !== "general"}
        >
          {activeTab === "general" ? <GeneralGuideOverview /> : null}
        </div>

        <div
          id={operationalPanelId}
          role="tabpanel"
          aria-labelledby={operationalTabId}
          hidden={activeTab !== "operational"}
        >
          {activeTab === "operational" ? <OperationalGuideOverview /> : null}
        </div>
      </div>
    </ModalFrame>
  );
}
