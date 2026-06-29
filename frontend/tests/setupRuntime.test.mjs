import test from "node:test";
import assert from "node:assert/strict";

import { applyRuntimePreset, DEFAULT_RUNTIME_PRESETS, providerFormErrors, readinessTone, runtimePresets } from "../src/setupRuntime.js";

test("runtimePresets falls back to default presets", () => {
  assert.equal(runtimePresets().length, 3);
  assert.equal(runtimePresets()[0].label, "llama.cpp");
});

test("applyRuntimePreset seeds URL, model, and limits", () => {
  const preset = DEFAULT_RUNTIME_PRESETS[2];
  const updated = applyRuntimePreset({ embeddings_model_name: "embed" }, preset);

  assert.equal(updated.llama_base_url, "http://127.0.0.1:11434/v1");
  assert.equal(updated.model_name, "llama3.1");
  assert.equal(updated.llm_model_name, "llama3.1");
  assert.equal(updated.context_window, 32768);
  assert.equal(updated.max_output_tokens, 1800);
  assert.equal(updated.runtime_preset, "ollama_gateway");
});

test("providerFormErrors catches missing and invalid values", () => {
  const errors = providerFormErrors({
    llama_base_url: "",
    model_name: "",
    embeddings_model_name: "",
    context_window: 1024,
    max_output_tokens: 17000,
  });

  assert.equal(errors.llama_base_url, "Model endpoint is required.");
  assert.equal(errors.model_name, "Model name is required.");
  assert.equal(errors.embeddings_model_name, "Embedding model is required.");
  assert.equal(errors.context_window, "Context window must be at least 2048.");
  assert.equal(errors.max_output_tokens, "Max output tokens must be between 256 and 16000.");
});

test("readinessTone distinguishes ready, partial, and failing states", () => {
  assert.equal(readinessTone({ ready: true }), "completed");
  assert.equal(readinessTone({ reachable: true, ready: false }), "warning");
  assert.equal(readinessTone({ ready: false }), "failed");
});
