# SpecForge Agent Rules

## Mission
- Move the project forward with the least wasted work possible.
- Prefer changes that improve shipping speed, runtime stability, and maintainability at the same time.
- Treat caches, persisted state, prompt memory, and derived artifacts as accelerators for future work, not disposable clutter.

## Execution Defaults
- Reuse the existing `specforge/` service layer before introducing new parallel logic.
- Favor incremental forward-compatible migrations over big rewrites that strand working code.
- Keep local-first behavior intact. The app should continue to work without cloud dependencies.
- Optimize for fast iteration on localhost. Choose workflows that reduce full-page reruns, repeated model setup, repeated prompt reconstruction, and repeated data fetching.
- Preserve caches and reuse expensive work where practical:
  - reuse SQLite state instead of rebuilding in-memory state repeatedly
  - reuse llama.cpp server state instead of restarting unnecessarily
  - reuse prompt-memory summaries instead of replaying large raw histories
  - reuse frontend-fetched data through targeted refreshes instead of broad reloads

## Rolling Todo Log
- Before starting substantial implementation work, record the task in `docs/TODO_LOG.md`.
- Every todo entry must include:
  - unique id
  - title
  - status
  - date and time added
  - date and time completed
  - owner
  - notes
- When work begins, mark the item `in_progress`.
- When work finishes, mark the item `completed` and fill in the completion timestamp.
- If work is intentionally deferred, mark it `deferred` and explain why.
- Do not delete old todo items. Keep a rolling history so humans can understand sequence, intent, and pace over time.

## Layer Tracking
- Record meaningful layer-level changes as they happen.
- When generation behavior changes for Layer 1, Layer 2, or Layer 3, note the affected layer in `docs/TODO_LOG.md`.
- If a change spans multiple layers, list all impacted layers explicitly.
- When adding new architecture, document whether it is:
  - UI only
  - API only
  - shared service logic
  - storage or memory behavior

## Human Readability
- Write code for humans first.
- Use clear names over clever names.
- Add comments for all new functions.
- Comments should explain intent, assumptions, or non-obvious control flow, not restate syntax.
- If a function has side effects, state that clearly in its comment or docstring.
- Keep files navigable: prefer small helpers with focused responsibilities.

## Refactor Triggers
You must proactively refactor code only when one of the following structural triggers is met. Do not refactor purely for aesthetic preferences unless explicitly ordered by the user.

### Trigger 1: The Rule of Three (Duplication)
- Rule: If the exact same logic, complex conditional, or block of code appears in three or more places, abstract it into a single, reusable helper function or module.
- Agent Action: Replace the duplicated blocks with the new helper function and ensure clean parameter passing.

### Trigger 2: Function Cognitive Load (Length and Scope)
- Rule: A single function should do one thing and do it well.
- Agent Action: Break down a function if it exceeds 40 lines of core logic, excluding docstrings/comments, or contains more than 3 nested levels of loops/conditionals. Extract the inner logic into smaller, well-named sub-functions.

### Trigger 3: Brittle Branching (Complex Conditionals)
- Rule: Complex, multi-variable if/else chains or deeply nested logic are highly prone to edge-case bugs.
- Agent Action: Refactor long if/else or switch-style blocks using guard clauses or configuration lookups to flatten the function layout.

## Verification
- After code changes, run the narrowest useful verification first, then broader validation if needed.
- Prefer compile checks, unit tests, and local smoke tests over assumptions.
- If a new localhost workflow is added, verify both backend and frontend startup paths.

## Documentation Discipline
- Update `README.md` when run commands or UX entrypoints change.
- Update `docs/TODO_LOG.md` as part of the work, not afterward as an optional cleanup.
- Keep prompt instructions centralized and editable outside core logic whenever practical.
