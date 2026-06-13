# SpecForge

SpecForge is a local recursive product-spec generator built around GGUF models served through `llama.cpp`.

## MVP capabilities

- Create a project from a product idea
- Generate Layer 1 feature pillars
- Broaden Layer 1 and Layer 2 until saturation using multi-pass generation
- Run Layer 1 across a sequence of local models for explorer/challenger coverage
- Cluster Layer 1 pillars into canonical families and score pillar quality before review
- Review nodes with keep, cut, rename, and priority controls
- Generate Layer 2 subfeatures for selected pillars
- Generate Layer 3 implementation specs for selected subfeatures
- Detect possible duplicates with fuzzy matching
- Maintain compressed generation memory and coverage summaries in SQLite
- Export the project tree to Markdown and JSON

## Project structure

```text
specforge/
  app.py
  prompts.json
  requirements.txt
  README.md
  specforge/
    __init__.py
    config.py
    db.py
    dedupe.py
    export.py
    generation.py
    llm.py
    models.py
    prompts.py
    tree.py
  data/
  exports/
```

## Prompt editing

All system prompts and prompt templates now live in one editable file:

- [prompts.json](C:/Users/Fresc/Feature_gen/prompts.json)

The Python code injects runtime context into those templates instead of hardcoding the prompt copy in the generation logic.

## Setup

```powershell
cd C:\Users\Fresc\Feature_gen
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Start llama.cpp server

SpecForge auto-discovers GGUF models under `C:\Users\Fresc\.cache\lm-studio\models` and prefers the Qwen 3.6 27B no-thinking model when available.
It also prefers the CUDA-enabled `llama-server.exe` bundled by LM Studio when found on this machine.

Example launch command:

```powershell
& "C:\Users\Fresc\.cache\lm-studio\extensions\backends\llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.21.0\llama-server.exe" `
  -m "C:\Users\Fresc\.cache\lm-studio\models\lmstudio-community\Qwen 3.6 27b q3_k_m_gguf-no-thinking\Qwen3.6-27B-Q3_K_M.gguf" `
  -c 32768 `
  -ngl 35 `
  --host 127.0.0.1 `
  --port 8080 `
  --reasoning off `
  --reasoning-format none `
  --reasoning-budget 0 `
  --alias "qwen-27b-q3-no-thinking" `
  --jinja `
  --no-ui
```

If your executable is not on `PATH`, set `LLAMA_SERVER_EXE` and use the command shown in the app sidebar.

## Run the app

```powershell
streamlit run app.py
```

## One-click launch

```powershell
powershell -ExecutionPolicy Bypass -File .\start_specforge.ps1
```

This script:

- starts the CUDA `llama-server.exe` in the background
- forces the no-thinking 27B GGUF
- sets reasoning budget to `0`
- waits for the local API to become healthy
- starts Streamlit
- opens the app in your browser

To stop both background processes:

```powershell
powershell -ExecutionPolicy Bypass -File .\stop_specforge.ps1
```

## Notes

- The app calls the `llama.cpp` server over HTTP at `http://127.0.0.1:8080/v1/chat/completions` by default.
- Rejected directions are derived from nodes you mark as `cut` and are fed back into future prompts.
- Possible duplicates are flagged before new nodes are inserted, but never auto-deleted.
- Broadening mode uses a generator plus critic/summarizer loop to keep expanding until novelty drops or coverage saturates.
- Layer 1 can sequence multiple local GGUF models and tracks source model provenance on generated pillars.
- Layer 1 now adds canonical pillar clustering, pillar-quality scoring, and merge/rename suggestions into node metadata.
- The working behavior spec lives in [docs/README.md](C:/Users/Fresc/Feature_gen/docs/README.md).
