import BriefWorkspace from "../BriefWorkspace";
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

function PreviewSection({ label, value, list = false }) {
  const content = list ? listItems(value) : value?.trim() || "Not captured yet";
  return (
    <section className="brief-preview-card">
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
  onPublish,
  onResearch,
  onProceed,
  researchJobState,
  onCancelJob,
}) {
  const compact = useIsCompactWorkspace();
  const liveBrief = brief || {};
  const researchRunning = researchJobState?.state === "running";
  const published = liveBrief.status === "published";
  const canProceed = published;
  const proceedDisabledReason = published ? "" : "Publish Layer 0 before moving to L1 Pillars.";

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
              onClick={onResearch}
              disabled={researchRunning}
              disabledReason={researchRunning ? "Market research is already running." : ""}
            >
              Research all
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
      <div className={compact ? "layer0-canonical-layout compact" : "layer0-canonical-layout"}>
        <div className="layer0-editor-column">
          <BriefWorkspace
            brief={liveBrief}
            conversation={conversation}
            onSave={onSave}
            onChat={onChat}
            onProceed={onProceed}
            canProceed={canProceed}
            proceedDisabledReason={proceedDisabledReason}
            compact={compact}
          />
          <WorkspaceJobNotice jobState={researchJobState} label="Market research" onCancel={onCancelJob} />
        </div>

        <aside className="layer0-preview-pane panel" aria-label="Canonical Layer 0 brief preview">
          <div className="layer0-preview-head canonical-preview-head">
            <div>
              <span className="workspace-eyebrow">Brief Preview</span>
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

          <div className="brief-preview-stack">
            <PreviewSection label="Summary" value={liveBrief.product_idea} />
            <PreviewSection label="Problem" value={liveBrief.problem} />
            <PreviewSection label="Target users" value={liveBrief.target_users} />
            <PreviewSection label="Constraints" value={liveBrief.constraints} />
            <PreviewSection label="Goals" value={liveBrief.goals} list />
            <PreviewSection label="Competitors" value={liveBrief.known_competitors} list />
            <PreviewSection label="Preferred directions" value={liveBrief.preferred_directions} list />
            <PreviewSection label="Rejected directions" value={liveBrief.rejected_directions} list />
            {liveBrief.notes?.trim() ? <PreviewSection label="Internal notes" value={liveBrief.notes} /> : null}
          </div>
        </aside>
      </div>
    </WorkspacePageLayout>
  );
}
