# Storage And Memory

Strata should keep the database as the source of truth and use compressed memory for prompting.

## SQLite tables

- `projects`: project identity and product idea
- `nodes`: the tree of generated ideas
- `generations`: raw prompts and model responses
- `project_memory`: compressed coverage summaries and critic output

## Memory behavior

- Do not feed the entire generation history back into the model.
- Keep compressed coverage summaries, overlap clusters, uncovered areas, and rejected ideas.
- Let the database store the detailed history while the prompt receives only the compact state needed for the next round.

## Deduplication

- Use fuzzy matching to catch near-duplicate titles and descriptions.
- Mark possible duplicates rather than deleting them automatically.
- Allow the user to decide what should be kept, merged, or cut.

## Performance behavior

- Prefer indexed, repeated reads over scanning the entire table each time.
- Keep layer-specific memory scoped to the relevant parent item.
- Preserve priority when editing nodes unless the user explicitly clears it.
