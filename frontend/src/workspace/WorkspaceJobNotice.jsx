function jobLabel(job) {
  const workflow = job?.request_payload?.research_job_type || job?.workflow || job?.job_type || "job";
  return String(workflow).replaceAll("_", " ");
}

export default function WorkspaceJobNotice({ jobState, label, onCancel }) {
  const job = jobState?.job;
  if (!job || !["queued", "running"].includes(job.status)) return null;
  const canCancel = Boolean(onCancel && job.kind && job.workflow);
  return (
    <div className="workspace-job-notice panel" role="status" aria-live="polite">
      <div>
        <strong>{label || jobLabel(job)} is {job.status}</strong>
        <p className="muted">
          {job.current_step || "Queued"}{Number.isFinite(Number(job.progress)) ? ` | ${Number(job.progress)}%` : ""}
          {job.id ? ` | job ${String(job.id).slice(0, 8)}` : ""}
        </p>
      </div>
      <button type="button" className="secondary-button danger-button" onClick={() => onCancel?.(job.id)} disabled={!canCancel}>
        Cancel
      </button>
    </div>
  );
}
