import { useState } from "react";
import BriefWorkspace from "../BriefWorkspace";
import { useIsCompactWorkspace } from "./workspaceSelectors";
import WorkspacePageLayout, { WorkspaceActionButton, WorkspaceActionGroup } from "./WorkspacePage";
import WorkspaceJobNotice from "./WorkspaceJobNotice";

function listItems(value) {
  return Array.isArray(value) && value.length ? value : ["Not captured yet"];
}

export default function Layer0View({
  brief,
  conversation,
  onSave,
  onChat,
  onPublish,
  onResearch,
  researchJobState,
  onCancelJob,
}) {
  const compact = useIsCompactWorkspace();
  const [previewOpen, setPreviewOpen] = useState(true);
  const liveBrief = brief || {};
  const researchRunning = researchJobState?.state === "running";
  const published = liveBrief.status === "published";
  const hasLiveBriefContent = Boolean(
    liveBrief.product_idea?.trim()
    || liveBrief.target_users?.trim()
    || liveBrief.constraints?.trim()
    || liveBrief.notes?.trim()
    || liveBrief.goals?.length
    || liveBrief.known_competitors?.length
    || liveBrief.preferred_directions?.length
    || liveBrief.rejected_directions?.length
  );
  return (
    <WorkspacePageLayout
      id="workspace-panel-layer0"
      ariaLabel="Layer 0 workspace"
      className="layer0-view"
      title="Product Idea"
      description="Shape the product brief, audience, constraints, goals, and known directions before downstream generation."
      status={liveBrief.status || "draft"}
      actions={(
        <WorkspaceActionGroup label="Controls">
          <div className="layer0-action-row">
            <div className="layer0-primary-actions">
              <WorkspaceActionButton
                secondary
                onClick={onPublish}
                disabled={published || !hasLiveBriefContent}
                disabledReason={
                  published
                    ? "This brief is already published."
                    : !hasLiveBriefContent
                      ? "Add some Layer 0 brief content before publishing."
                      : ""
                }
              >
                Publish
              </WorkspaceActionButton>
              <WorkspaceActionButton
                secondary
                onClick={onResearch}
                disabled={researchRunning}
                disabledReason={researchRunning ? "Market research is already running." : ""}
              >
                {researchJobState?.state === "failed" ? "Research all" : "Research all"}
              </WorkspaceActionButton>
            </div>
            {!previewOpen ? (
              <WorkspaceActionButton
                className="layer0-preview-toggle"
                secondary
                onClick={() => setPreviewOpen(true)}
                disabled={!hasLiveBriefContent}
                disabledReason={!hasLiveBriefContent ? "Add some brief content before opening the live preview." : ""}
              >
                Preview live brief
              </WorkspaceActionButton>
            ) : null}
          </div>
          {researchJobState?.state === "failed" ? <span className="warning">Latest research failed. Retry when the runtime is ready.</span> : null}
        </WorkspaceActionGroup>
      )}
    >
      <div className={`${compact ? "layer0-split compact" : "layer0-split"} ${previewOpen ? "" : "preview-closed"}`}>
        <div className="layer0-input-pane">
          <BriefWorkspace
            brief={liveBrief}
            conversation={conversation}
            onSave={onSave}
            onChat={onChat}
            compact
          />
          <WorkspaceJobNotice jobState={researchJobState} label="Market research" onCancel={onCancelJob} />
        </div>
        {previewOpen ? (
          <aside className="layer0-preview-pane panel" aria-label="Live Layer 0 brief preview">
            <div className="layer0-preview-head">
              <span className="workspace-eyebrow">Live brief</span>
              <button type="button" className="icon-button layer0-preview-close" onClick={() => setPreviewOpen(false)} aria-label="Close live brief preview" title="Close live brief preview">
                x
              </button>
            </div>
            <h3>{liveBrief.product_idea || "Product idea"}</h3>
            <dl className="brief-preview-list">
              <div>
                <dt>Target users</dt>
                <dd>{liveBrief.target_users || "Not captured yet"}</dd>
              </div>
              <div>
                <dt>Constraints</dt>
                <dd>{liveBrief.constraints || "Not captured yet"}</dd>
              </div>
              <div>
                <dt>Goals</dt>
                <dd>{listItems(liveBrief.goals).join(", ")}</dd>
              </div>
              <div>
                <dt>Competitors</dt>
                <dd>{listItems(liveBrief.known_competitors).join(", ")}</dd>
              </div>
              <div>
                <dt>Preferred directions</dt>
                <dd>{listItems(liveBrief.preferred_directions).join(", ")}</dd>
              </div>
              <div>
                <dt>Rejected directions</dt>
                <dd>{listItems(liveBrief.rejected_directions).join(", ")}</dd>
              </div>
            </dl>
            {liveBrief.notes ? <p className="muted">{liveBrief.notes}</p> : null}
          </aside>
        ) : null}
      </div>
    </WorkspacePageLayout>
  );
}
