import { useState } from "react";

const RUNTIME_PRESETS = [
  { label: "llama.cpp", llama_base_url: "http://127.0.0.1:8080", model_name: "local-model" },
  { label: "LM Studio", llama_base_url: "http://127.0.0.1:1234", model_name: "local-model" },
  { label: "Ollama gateway", llama_base_url: "http://127.0.0.1:11434/v1", model_name: "llama3.1" },
];

export default function SetupWizard({ defaults, apiFetch, onComplete }) {
  const [form, setForm] = useState({
    llama_base_url: defaults?.llama_base_url || "http://127.0.0.1:8080",
    model_name: defaults?.model_name || "local-model",
    embeddings_enabled: defaults?.embeddings_enabled ?? true,
    embeddings_model_name: defaults?.embeddings_model_name || "sentence-transformers/all-MiniLM-L6-v2",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch("/setup/complete", { method: "POST", body: JSON.stringify(form) });
      onComplete(result);
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  function applyPreset(preset) {
    setForm({ ...form, llama_base_url: preset.llama_base_url, model_name: preset.model_name });
  }

  return (
    <main className="setup-screen">
      <form className="panel setup-card" onSubmit={submit}>
        <span className="eyebrow">First-run setup</span>
        <h1>Connect Strata to your model</h1>
        <p className="muted">Strata stays on this machine. Connect any OpenAI-compatible endpoint, including llama.cpp, LM Studio, Ollama-compatible gateways, or a remote provider proxy.</p>
        <div className="button-row compact" aria-label="Runtime presets">
          {RUNTIME_PRESETS.map((preset) => (
            <button key={preset.label} type="button" className="secondary-button" onClick={() => applyPreset(preset)}>{preset.label}</button>
          ))}
        </div>
        <label>Model endpoint<input value={form.llama_base_url} onChange={(event) => setForm({ ...form, llama_base_url: event.target.value })} /></label>
        <label>Model name<input value={form.model_name} onChange={(event) => setForm({ ...form, model_name: event.target.value })} /></label>
        <label className="checkbox-item"><input type="checkbox" checked={form.embeddings_enabled} onChange={(event) => setForm({ ...form, embeddings_enabled: event.target.checked })} /> Enable local embeddings</label>
        {form.embeddings_enabled ? <label>Embedding model<input value={form.embeddings_model_name} onChange={(event) => setForm({ ...form, embeddings_model_name: event.target.value })} /></label> : null}
        {error ? <div className="error-banner">{error}</div> : null}
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Finish setup"}</button>
        <p className="muted">The model may remain offline during setup. You can still inspect projects and settings, but generation, research, assistant replies, replay, and audits wait until a compatible model endpoint is reachable.</p>
      </form>
    </main>
  );
}
