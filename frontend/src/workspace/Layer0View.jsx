import { useState } from "react";
import BriefWorkspace from "../BriefWorkspace";
import { useIsCompactWorkspace } from "./workspaceSelectors";

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
}) {
  const compact = useIsCompactWorkspace();
  const [previewOpen, setPreviewOpen] = useState(true);
  const liveBrief = brief || {};
  const researchRunning = researchJobState?.state === "running";

  return (
    <section className="workspace-layer-panel layer0-view" id="workspace-panel-layer0" role="tabpanel" aria-label="Layer 0 workspace">
      <div className={`${compact ? "layer0-split compact" : "layer0-split"} ${previewOpen ? "" : "preview-closed"}`}>
        <div className="layer0-input-pane">
          {!previewOpen ? (
            <div className="layer0-preview-reopen">
              <button type="button" className="secondary-button" onClick={() => setPreviewOpen(true)}>
                Preview live brief
              </button>
            </div>
          ) : null}
          <BriefWorkspace
            brief={liveBrief}
            conversation={conversation}
            onSave={onSave}
            onChat={onChat}
            onPublish={onPublish}
            compact
          />
          <div className="workspace-toolbar panel">
            <button type="button" className="secondary-button" onClick={onResearch} disabled={researchRunning}>
              {researchRunning ? "Research running..." : researchJobState?.state === "failed" ? "Retry market research" : "Run market research"}
            </button>
            {researchJobState?.state === "failed" ? <span className="warning">Latest research failed. Retry when the runtime is ready.</span> : null}
          </div>
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
    </section>
  );
}
