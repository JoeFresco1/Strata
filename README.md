# SpecForge

SpecForge is a local recursive product-spec generator built around GGUF models served through `llama.cpp`.
The default UX runs as a localhost app with `FastAPI + React`, and the default database now runs on a repo-local `PostgreSQL + pgvector` cluster.

## MVP capabilities

- Create a project from a product idea
- Work Layer 0 as a draft brief with switchable Plan mode chat and Form mode structured editing
- Configure project-scoped LLM and embedding profiles, including OpenAI-compatible API endpoints and local GGUF/model paths
- Publish the Layer 0 brief as the only source of truth before unlocking Layer 1
- Run fully local/free competitor research from user seeds, local model suggestions, free search-result scraping, focused crawling, local extraction, local embeddings, and llama.cpp-compatible synthesis
- Review Layer 0 market findings and Layer 1 pillar coverage matrices with URLs, snippets, adoption status, coverage status, and confidence
- Visualize each project as a product map rooted in Layer 0 with branch detail and overlap signals
- Generate Layer 1 feature pillars
- Broaden Layer 1 and Layer 2 until saturation using multi-pass generation
- Run Layer 1 across a sequence of local models for explorer/challenger coverage
- Cluster Layer 1 pillars into canonical families and score pillar quality before review
- Keep Layer 1 prompt memory source-typed so user-confirmed, persisted-system, and critic-inferred signals stay separate
- Review nodes with keep, cut, rename, and priority controls
- Generate Layer 2 subfeatures for selected pillars
- Generate Layer 3 implementation specs for selected subfeatures
- Use canonical families as a hard duplicate stop and semantic similarity in `pgvector` as the primary overlap signal
- Keep fuzzy lexical matching as supporting metadata instead of the main Layer 1 duplicate veto
- Maintain compressed generation memory and coverage summaries in PostgreSQL
- Store projects, nodes, generation logs, and future retrieval memory in PostgreSQL
- Enable `pgvector` now so retrieval and semantic dedupe can grow in-place later
- Export the project tree to Markdown and JSON
- Run the UI locally through a React app backed by a FastAPI API

## Project structure

```text
specforge/
  AGENTS.md
  prompts.json
  requirements.txt
  README.md
  serve_api.py
  start_local_postgres.ps1
  stop_local_postgres.ps1
  frontend/
    package.json
    src/
  specforge/
    __init__.py
    api.py
    api_models.py
    brief.py
    config.py
    db.py
    dedupe.py
    export.py
    generation.py
    llm.py
    models.py
    prompts.py
    research.py
    tree.py
  data/
  .local/
  docs/
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
cd frontend
npm install
cd ..
```

## Local PostgreSQL + pgvector

SpecForge now defaults to a repo-local PostgreSQL cluster under `.local/postgres-data` on port `55433`.
That avoids relying on a passworded machine-wide service and keeps the project self-contained.

The default env values are:

```powershell
SPECFORGE_DB_BACKEND=postgres
SPECFORGE_DATABASE_URL=postgresql://postgres@127.0.0.1:55433/specforge
SPECFORGE_POSTGRES_ADMIN_URL=postgresql://postgres@127.0.0.1:55433/postgres
SPECFORGE_EMBEDDINGS_ENABLED=true
SPECFORGE_EMBEDDINGS_MODEL=sentence-transformers/all-MiniLM-L6-v2
SPECFORGE_EMBEDDINGS_INSECURE_DOWNLOAD_FALLBACK=true
SPECFORGE_PILLAR_SIMILARITY_THRESHOLD=0.78
SPECFORGE_PILLAR_SIMILARITY_BLOCK_THRESHOLD=0.9
```

You can start or stop the local database directly:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_local_postgres.ps1
powershell -ExecutionPolicy Bypass -File .\stop_local_postgres.ps1
```

On first boot, SpecForge will:

- initialize the local PostgreSQL cluster if it does not exist
- create the `specforge` database if it does not exist
- enable the `vector` extension
- import the legacy SQLite dataset from `data/specforge.db` if the new Postgres database is empty
- keep Layer 1 embedding vectors in `node_embeddings` for cosine-similarity lookups

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

## Run the localhost app

```powershell
powershell -ExecutionPolicy Bypass -File .\start_specforge.ps1
```

This starts:

- the repo-local PostgreSQL cluster on `127.0.0.1:55433`
- the CUDA `llama-server.exe` in the background
- the FastAPI backend on `http://127.0.0.1:8000`
- the React frontend on `http://127.0.0.1:5173`
- your browser pointed at the React app

The launcher reuses existing local state and installs frontend packages automatically if `frontend/node_modules` is missing.

## Layer 0 brief and local research

Layer 0 is now a draft brief workspace. Plan mode lets you chat with the local model while SpecForge extracts structured fields into the same canonical brief that Form mode edits directly. The v1 brief fields are:

- `product_idea`
- `known_competitors`
- `constraints`
- `target_users`
- `goals`
- `preferred_directions`
- `rejected_directions`
- `notes`
- `status`

Layer 1 generation is blocked until the brief is published. Publishing marks the brief `published`, queues Layer 0 competitor research, and makes the published brief the source of truth for Layer 1.

Each project also has a `Settings` tab where you can:

- define multiple LLM profiles with an API base URL, model name, and optional local GGUF path
- define multiple embedding profiles with a Hugging Face model id or local model path
- assign specific models to Layer 0 chat, Layer 0 extraction, Layer 1 generation, Layer 2 generation, Layer 3 generation, Layer 0 research, Layer 1 research, Layer 1 similarity embeddings, and research embeddings

Research stays local/free:

- user-provided competitor seeds are highest priority
- the local llama.cpp model can suggest additional competitors
- public search discovery scrapes free HTML result pages
- focused crawling extracts a small set of public competitor pages
- `trafilatura` is the primary extractor, with BeautifulSoup text fallback
- extracted chunks are embedded locally and stored in PostgreSQL/pgvector
- findings include URLs and snippets for human review

Rerun controls are available for Layer 0, all Layer 1 pillars, or one pillar from the review coverage matrix. Editing a generated pillar marks that pillar's research stale until rerun.

## Manual localhost commands

Backend:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn serve_api:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

To stop both background processes:

```powershell
powershell -ExecutionPolicy Bypass -File .\stop_specforge.ps1
```

## Legacy Streamlit shell

The old Streamlit UI code still exists in [specforge/app_ui.py](C:/Users/Fresc/Feature_gen/specforge/app_ui.py) as a fallback reference, but the active UX direction is the localhost `FastAPI + React` app.

## Agent workflow

- Project operating rules live in [AGENTS.md](C:/Users/Fresc/Feature_gen/AGENTS.md).
- Rolling work history lives in [docs/TODO_LOG.md](C:/Users/Fresc/Feature_gen/docs/TODO_LOG.md).

## Notes

- The app calls the `llama.cpp` server over HTTP at `http://127.0.0.1:8080/v1/chat/completions` by default.
- The primary database now runs on the repo-local PostgreSQL cluster instead of SQLite.
- `pgvector` is enabled at bootstrap time and now stores Layer 1 pillar embeddings for semantic-overlap checks.
- Rejected directions are derived from nodes you mark as `cut` and are fed back into future prompts.
- Canonical family duplicates are blocked before insert, while fuzzy lexical similarity is kept as supporting review metadata.
- Broadening mode uses a generator plus critic/summarizer loop to keep expanding until novelty drops or coverage saturates.
- Layer 1 can sequence multiple local GGUF models and tracks source model provenance on generated pillars.
- Layer 1 now separates user-confirmed memory from persisted system state and critic-inferred guidance inside the generation prompt.
- Critic-suggested lenses are now advisory rather than directive, and challenger rounds intentionally use a lighter state slice to reduce frame inheritance.
- Layer 1 now adds canonical pillar clustering, pillar-quality scoring, and merge/rename suggestions into node metadata.
- Layer 1 review now also shows embedding-based overlap warnings sourced from cosine similarity against existing pillars.
- Layer 0 publish is the only transition into Layer 1, and competitor findings are advisory review evidence rather than automatic pruning rules.
- The localhost API exposes project snapshots, node updates, generation actions, and export actions for the React client.
- The working behavior spec lives in [docs/README.md](C:/Users/Fresc/Feature_gen/docs/README.md).
