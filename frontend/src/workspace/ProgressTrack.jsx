import { PROGRESS_STEPS, statusLabel } from "./workspaceSelectors";

export default function ProgressTrack({ layerStatus }) {
  return (
    <nav className="workspace-progress" aria-label="Project progress">
      {PROGRESS_STEPS.map((step, index) => {
        const state = layerStatus[step.statusKey] || { status: "locked", label: "Locked" };
        return (
          <div key={step.id} className={`workspace-progress-step ${state.status}`}>
            <span className="workspace-progress-index">{index + 1}</span>
            <span className="workspace-progress-label">{step.label}</span>
            <small>{statusLabel(state.status)}</small>
          </div>
        );
      })}
    </nav>
  );
}

