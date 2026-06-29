export const DEFAULT_RUNTIME_PRESETS = [
  { id: "llama_cpp", label: "llama.cpp", llama_base_url: "http://127.0.0.1:8080", model_name: "local-model", context_window: 32768, max_output_tokens: 1800 },
  { id: "lm_studio", label: "LM Studio", llama_base_url: "http://127.0.0.1:1234", model_name: "local-model", context_window: 32768, max_output_tokens: 1800 },
  { id: "ollama_gateway", label: "Ollama gateway", llama_base_url: "http://127.0.0.1:11434/v1", model_name: "llama3.1", context_window: 32768, max_output_tokens: 1800 },
];

export function runtimePresets(configPresets) {
  return Array.isArray(configPresets) && configPresets.length ? configPresets : DEFAULT_RUNTIME_PRESETS;
}

export function applyRuntimePreset(form, preset) {
  return {
    ...form,
    llama_base_url: preset.llama_base_url,
    model_name: preset.model_name,
    llm_model_name: preset.model_name,
    context_window: preset.context_window,
    max_output_tokens: preset.max_output_tokens,
    runtime_preset: preset.id || "",
  };
}

export function providerFormErrors(form) {
  const errors = {};
  if (!String(form.llama_base_url || "").trim()) errors.llama_base_url = "Model endpoint is required.";
  if (!String(form.model_name || form.llm_model_name || "").trim()) errors.model_name = "Model name is required.";
  if (!String(form.embeddings_model_name || "").trim()) errors.embeddings_model_name = "Embedding model is required.";
  const contextWindow = Number(form.context_window || 0);
  if (!Number.isFinite(contextWindow) || contextWindow < 2048) errors.context_window = "Context window must be at least 2048.";
  const maxOutputTokens = Number(form.max_output_tokens || 0);
  if (!Number.isFinite(maxOutputTokens) || maxOutputTokens < 256 || maxOutputTokens > 16000) {
    errors.max_output_tokens = "Max output tokens must be between 256 and 16000.";
  }
  return errors;
}

export function readinessTone(readiness) {
  if (readiness?.ready) return "completed";
  if (readiness?.reachable || readiness?.auth_ok || readiness?.model_listed) return "warning";
  return "failed";
}
