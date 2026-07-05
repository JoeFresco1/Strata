import { useState } from "react";
import { applyRuntimePreset, providerFormErrors, readinessTone, runtimePresets } from "./setupRuntime";

export default function SetupWizard({ defaults, apiFetch, onComplete }) {
  const [form, setForm] = useState({
    llama_base_url: defaults?.llama_base_url || "http://127.0.0.1:8080",
    model_name: defaults?.model_name || "local-model",
    embeddings_enabled: defaults?.embeddings_enabled ?? true,
    embeddings_model_name: defaults?.embeddings_model_name || "sentence-transformers/all-MiniLM-L6-v2",
    bearer_token: "",
    clear_bearer_token: false,
    context_window: defaults?.context_window || 32768,
    max_output_tokens: defaults?.max_output_tokens || 1800,
    runtime_preset: defaults?.runtime_preset || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [setupReadiness, setSetupReadiness] = useState(defaults?.provider_readiness || {});

  async function submit(event) {
    event.preventDefault();
    const nextErrors = providerFormErrors(form);
    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch("/setup/complete", { method: "POST", body: JSON.stringify(form) });
      setSetupReadiness(result.provider_readiness || {});
      onComplete(result);
    } catch (submitError) {
      setError(submitError.message);
      if (submitError.detailPayload?.provider_readiness) {
        setSetupReadiness(submitError.detailPayload.provider_readiness);
      }
    } finally {
      setBusy(false);
    }
  }

  function applyPreset(preset) {
    setForm((current) => applyRuntimePreset(current, preset));
    setFieldErrors({});
  }

  const readiness = setupReadiness;
  const presets = runtimePresets(defaults?.runtime_presets);
  const tokenSaved = defaults?.has_bearer_token;

  return (
    <main className="setup-screen">
      <form className="panel setup-card" onSubmit={submit}>
        <h1>Connect Strata to your model</h1>
        <p className="muted">Strata stays on this machine. Connect any OpenAI-compatible endpoint, including llama.cpp, LM Studio, Ollama-compatible gateways, or a remote provider proxy.</p>
        <div className="button-row compact" aria-label="Runtime presets">
          {presets.map((preset) => (
            <button key={preset.id || preset.label} type="button" className="secondary-button" onClick={() => applyPreset(preset)}>{preset.label}</button>
          ))}
        </div>
        <label>Model endpoint<input value={form.llama_base_url} onChange={(event) => setForm({ ...form, llama_base_url: event.target.value })} /></label>
        {fieldErrors.llama_base_url ? <div className="error-banner">{fieldErrors.llama_base_url}</div> : null}
        <label>Model name<input value={form.model_name} onChange={(event) => setForm({ ...form, model_name: event.target.value })} /></label>
        {fieldErrors.model_name ? <div className="error-banner">{fieldErrors.model_name}</div> : null}
        <label>Bearer token<input type="password" autoComplete="new-password" value={form.bearer_token} placeholder={tokenSaved ? "Token saved on server" : "Optional"} onChange={(event) => setForm({ ...form, bearer_token: event.target.value, clear_bearer_token: false })} /></label>
        <label className="checkbox-item"><input type="checkbox" checked={form.clear_bearer_token} onChange={(event) => setForm({ ...form, clear_bearer_token: event.target.checked, bearer_token: event.target.checked ? "" : form.bearer_token })} /> Remove saved bearer token</label>
        <div className="brief-grid">
          <label>Context window<input type="number" min="2048" value={form.context_window} onChange={(event) => setForm({ ...form, context_window: Number(event.target.value) })} /></label>
          <label>Max output tokens<input type="number" min="256" max="16000" value={form.max_output_tokens} onChange={(event) => setForm({ ...form, max_output_tokens: Number(event.target.value) })} /></label>
        </div>
        {fieldErrors.context_window ? <div className="error-banner">{fieldErrors.context_window}</div> : null}
        {fieldErrors.max_output_tokens ? <div className="error-banner">{fieldErrors.max_output_tokens}</div> : null}
        <label className="checkbox-item"><input type="checkbox" checked={form.embeddings_enabled} onChange={(event) => setForm({ ...form, embeddings_enabled: event.target.checked })} /> Enable local embeddings</label>
        {form.embeddings_enabled ? <label>Embedding model<input value={form.embeddings_model_name} onChange={(event) => setForm({ ...form, embeddings_model_name: event.target.value })} /></label> : null}
        {fieldErrors.embeddings_model_name ? <div className="error-banner">{fieldErrors.embeddings_model_name}</div> : null}
        {readiness?.message ? <div className={`status-card ${readinessTone(readiness)}`}>{readiness.message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}
        <button type="submit" disabled={busy}>{busy ? "Saving..." : "Finish setup"}</button>
        <p className="muted">The model may remain offline during setup. You can still inspect projects and settings, but generation, research, assistant replies, replay, and audits wait until a compatible model endpoint is reachable.</p>
      </form>
    </main>
  );
}
