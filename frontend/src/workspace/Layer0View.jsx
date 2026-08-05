import { useState } from "react";
import BriefWorkspace from "../BriefWorkspace";
import ProductDiscoveryPanel from "../ProductDiscoveryPanel";
import { useIsCompactWorkspace } from "./workspaceSelectors";
import WorkspacePageLayout, { WorkspaceActionButton, WorkspaceActionGroup } from "./WorkspacePage";
import WorkspaceJobNotice from "./WorkspaceJobNotice";

function listItems(value) {
  return Array.isArray(value) && value.length ? value : ["Not captured yet"];
}

function hasBriefContent(brief) {
  return Boolean(
    brief?.product_idea?.trim()
    || brief?.problem?.trim()
    || brief?.target_users?.trim()
    || brief?.constraints?.trim()
    || brief?.notes?.trim()
    || brief?.goals?.length
    || brief?.known_competitors?.length
    || brief?.preferred_directions?.length
    || brief?.rejected_directions?.length
  );
}

function formatLastUpdated(value) {
  if (!value) return "Not saved yet";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Not saved yet";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

function PreviewSection({ label, value, list = false, changed = false }) {
  const content = list ? listItems(value) : value?.trim() || "Not captured yet";
  return (
    <section className={`brief-preview-card${changed ? " recently-changed" : ""}`}>
      <div className="brief-preview-card-head">
        <span className="workspace-card-label">{label}</span>
      </div>
      {list ? (
        <ul className="brief-preview-bullets">
          {content.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : (
        <p>{content}</p>
      )}
    </section>
  );
}

export default function Layer0View({
  brief,
  conversation,
  onSave,
  onChat,
  onStopChat,
  onProposalDecision,
  onPublish,
  onResearch,
  onProceed,
  researchJobState,
  onCancelJob,
  discovery,
  discoveryJobState,
  competitorResearchJobState,
  onGenerateDiscovery,
  onDiscoveryRevisionAction,
  onDiscoveryEdit,
  onStartCompetitorResearch,
  onCompetitorResearchAction,
  onCompetitorResearchEdit,
  onAttachCompetitorResearch,
}) {
  const compact = useIsCompactWorkspace();
  const [mobileBriefOpen, setMobileBriefOpen] = useState(false);
  const [layer0Section, setLayer0Section] = useState("brief");
  const liveBrief = brief || {};
  const researchRunning = researchJobState?.state === "running";
  const published = liveBrief.status === "published";
  const canProceed = published;
  const proceedDisabledReason = published ? "" : "Publish Layer 0 before moving to L1 Pillars.";
  const latestApplied = [...(conversation || [])].reverse().find((turn) => (
    ["applied", "partially_applied"].includes(turn.extracted_updates?.proposal?.status)
  ));
  const changedFields = new Set(latestApplied?.extracted_updates?.proposal?.applied_fields || []);
  const staleProposal = [...(conversation || [])].reverse().find((turn) => turn.extracted_updates?.proposal?.status === "stale");

  return (
    <WorkspacePageLayout
      id="workspace-panel-layer0"
      ariaLabel="Layer 0 workspace"
      className="layer0-view"
      title="L0 Product Idea"
      description="Define the product concept, target users, constraints, goals, competitors, and rejected directions before generating pillars."
      status={liveBrief.status || "draft"}
      actions={(
        <WorkspaceActionGroup label="Brief actions">
          <div className="segmented-action-row layer0-primary-actions">
            <WorkspaceActionButton
              secondary
              onClick={onPublish}
              disabled={!hasBriefContent(liveBrief)}
              disabledReason={!hasBriefContent(liveBrief) ? "Add some Layer 0 brief content before publishing." : ""}
            >
              {published ? "Republish brief" : "Publish brief"}
            </WorkspaceActionButton>
            <span className="workspace-action-divider" aria-hidden="true" />
            <WorkspaceActionButton
              secondary
              onClick={onProceed}
              disabled={!canProceed}
              disabledReason={proceedDisabledReason}
            >
              Proceed to L1 Pillars
            </WorkspaceActionButton>
          </div>
          {researchJobState?.state === "failed" ? <span className="warning">Latest research failed. Retry when the runtime is ready.</span> : null}
        </WorkspaceActionGroup>
      )}
    >
      <nav className="layer0-section-tabs" aria-label="Layer 0 sections">
        <button type="button" className={layer0Section === "brief" ? "active" : ""} onClick={() => setLayer0Section("brief")}>Product Brief</button>
        <button
          type="button"
          className={layer0Section === "discovery" ? "active" : ""}
          onClick={() => setLayer0Section("discovery")}
          disabled={!published}
          title={!published ? "Publish the Product Brief to unlock Product Discovery." : ""}
        >
          Product Discovery
        </button>
      </nav>
      {layer0Section === "discovery" ? (
        <ProductDiscoveryPanel
          brief={liveBrief}
          discovery={discovery}
          generationJobState={discoveryJobState}
          researchJobState={competitorResearchJobState}
          onGenerate={onGenerateDiscovery}
          onRevisionAction={onDiscoveryRevisionAction}
          onDiscoveryEdit={onDiscoveryEdit}
          onStartResearch={onStartCompetitorResearch}
          onResearchAction={onCompetitorResearchAction}
          onResearchEdit={onCompetitorResearchEdit}
          onAttachResearch={onAttachCompetitorResearch}
          onCancelJob={onCancelJob}
        />
      ) : (
      <div className={compact ? "layer0-canonical-layout compact" : "layer0-canonical-layout"}>
        <div className="layer0-editor-column">
          <BriefWorkspace
            brief={liveBrief}
            conversation={conversation}
            onSave={onSave}
            onChat={onChat}
            onStopChat={onStopChat}
            onProposalDecision={onProposalDecision}
            onProceed={onProceed}
            canProceed={canProceed}
            proceedDisabledReason={proceedDisabledReason}
            compact={compact}
          />
          <WorkspaceJobNotice jobState={researchJobState} label="Market research" onCancel={onCancelJob} />
        </div>

        {compact ? (
          <button
            type="button"
            className="secondary-button layer0-mobile-brief-toggle"
            onClick={() => setMobileBriefOpen((current) => !current)}
            aria-expanded={mobileBriefOpen}
            aria-controls="layer0-canonical-brief"
          >
            {mobileBriefOpen ? "Hide saved brief" : "View saved brief"}
          </button>
        ) : null}

        <aside
          id="layer0-canonical-brief"
          className={`layer0-preview-pane panel${compact && !mobileBriefOpen ? " mobile-collapsed" : ""}`}
          aria-label="Canonical Layer 0 brief preview"
        >
          <div className="layer0-preview-head canonical-preview-head">
            <div>
              <span className="workspace-eyebrow">Saved source of truth</span>
              <h3>{liveBrief.product_idea || "Saved Layer 0 brief"}</h3>
              <p className="muted">This panel shows the canonical saved brief used by downstream layers.</p>
            </div>
            <div className="brief-preview-meta">
              <span className={`status-pill ${liveBrief.status || "draft"}`}>{liveBrief.status || "draft"}</span>
              <span className="brief-preview-updated">Last updated: {formatLastUpdated(liveBrief.updated_at)}</span>
            </div>
          </div>

          {published ? (
            <div className="brief-editor-notice warning">
              <strong>Downstream dependency</strong>
              <span>Changes to Layer 0 may require downstream review after you save and republish this brief.</span>
            </div>
          ) : null}

          {staleProposal ? (
            <div className="brief-editor-notice warning" role="status">
              <strong>Conversation proposal is stale</strong>
              <span>The saved brief changed after that proposal was prepared. Compare or regenerate it before applying.</span>
            </div>
          ) : null}

          <div className="brief-preview-stack">
            <PreviewSection label="Summary" value={liveBrief.product_idea} changed={changedFields.has("product_idea")} />
            <PreviewSection label="Problem" value={liveBrief.problem} changed={changedFields.has("problem")} />
            <PreviewSection label="Target users" value={liveBrief.target_users} changed={changedFields.has("target_users")} />
            <PreviewSection label="Constraints" value={liveBrief.constraints} changed={changedFields.has("constraints")} />
            <PreviewSection label="Goals" value={liveBrief.goals} list changed={changedFields.has("goals")} />
            <PreviewSection label="Competitors" value={liveBrief.known_competitors} list changed={changedFields.has("known_competitors")} />
            <PreviewSection label="Preferred directions" value={liveBrief.preferred_directions} list changed={changedFields.has("preferred_directions")} />
            <PreviewSection label="Rejected directions" value={liveBrief.rejected_directions} list changed={changedFields.has("rejected_directions")} />
            {liveBrief.notes?.trim() ? <PreviewSection label="Internal notes" value={liveBrief.notes} /> : null}
          </div>
        </aside>
      </div>
      )}
    </WorkspacePageLayout>
  );
}
