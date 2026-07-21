# README launch plan

This is the production brief for the visual assets and repository changes that should accompany Strata's public launch. The README is written to work without these assets; adding them will turn a strong technical landing page into a credible product launch page.

## Brand direction

### Logo

Use a geometric strata mark: three or four offset horizontal planes that align into one coherent form. It should communicate layered product definition without looking like a database, hamburger menu, or generic sparkle.

Requirements:

- recognizable at 16 px as a favicon and at 1280 px on a social card;
- one-color version first, then a restrained color version;
- no gradients in the core mark;
- pair with a custom or lightly modified wordmark, not a stock technology font;
- deliver SVG, transparent PNG, favicon sizes, and a square avatar lockup;
- test on GitHub light and dark themes.

Avoid brains, robots, magic wands, chat bubbles, network-node clichés, and literal geological illustrations.

### Color palette

| Role | Color | Use |
| --- | --- | --- |
| Ink | `#111827` | Primary text and dark surfaces |
| Paper | `#F8FAFC` | Light background |
| Strata violet | `#5B5BD6` | Brand mark, links, primary actions |
| Mineral blue | `#2563EB` | Information and graph relationships |
| Lichen green | `#15803D` | Approved and healthy states |
| Amber | `#D97706` | Review required and pre-release states |
| Fault red | `#B91C1C` | Destructive actions and failed states |

Keep the public brand mostly neutral. Violet should be an accent, not a full-page wash. Product screenshots should preserve real status colors rather than being recolored for marketing.

## Required screenshots

Capture one coherent example project at 1440 × 900, using realistic content that remains readable when GitHub scales the image down. Use a browser with no personal bookmarks, extensions, tokens, local paths, project IDs, or diagnostic data visible.

1. **Hero workspace** — the full project shell with the workflow stepper, populated map, selected entity, and context panel. This is the first-screen image.
2. **Canonical brief** — Layer 0 Plan mode or Form mode beside the Brief Preview, with a clear publish boundary.
3. **Pillar review** — Layer 1 with several plausible pillars and one overlap resolution, showing human control.
4. **Feature graph** — Layer 2 map with relationships, review state, and evidence without overwhelming density.
5. **Capability Design Card** — one strong Layer 3 card with behavior, options, constraints, decisions, and pressure-test state.
6. **Delivery** — export choices and a concise view of the resulting Markdown/JSON or Spec Kit bundle.
7. **Analytics** — token/cost/run/health visibility, used lower in the README or documentation rather than in the hero.
8. **Mobile** — one compact image proving the project library or review flow remains usable at a narrow width.

Recommended filenames:

```text
docs/assets/readme/
  strata-workspace-hero.webp
  strata-brief.webp
  strata-pillar-review.webp
  strata-feature-graph.webp
  strata-capability-design.webp
  strata-delivery.webp
  strata-analytics.webp
  strata-mobile.webp
```

Use WebP at roughly 180–300 KB per desktop image. Include descriptive alt text. Keep a lossless source outside the release package if future recrops are likely.

## Animated product loops

Record silent loops at 1440 × 900, 12–18 seconds each, with deliberate cursor movement and no waiting on a real model.

1. **Idea to published brief** — create project, switch between Plan and Form, show both updating one brief, publish.
2. **Pillars to feature map** — approve pillars, move to Layer 2, reveal the graph, select a feature, resolve an overlap.
3. **Capability to handoff** — open a Capability Design Card, make a human choice, approve, export the delivery bundle.

Ship MP4 for the website or release post and optimized GIF/WebP only where GitHub support requires it. Aim below 8 MB per README animation. Never simulate model quality; pre-seed a fixture and state that the loop is shortened.

## Social preview

Create a 1280 × 640 GitHub social preview with:

- logo and wordmark in the upper-left;
- headline: `Discover the product before you build it.`;
- one simplified Layer 0 → Layer 3 flow or cropped workspace visual;
- the violet accent on an ink or paper background;
- no badges, feature list, URL, tiny UI text, or more than one sentence.

Check the card at small mobile preview size. The mark and headline must still read before any interface detail does.

## Repository organization

Before a broad launch:

1. Rename the GitHub repository from `Spec_Forge` to `strata` and update clone URLs, badge URLs, package metadata, release links, and compatibility references.
2. Add issue templates for bug reports, product proposals, provider compatibility, and documentation.
3. Add a pull request template with verification, UI evidence, migration impact, privacy impact, and layer-boundary checks.
4. Publish a small `examples/` directory with one sanitized project archive and its exported Markdown/JSON output.
5. Add `docs/assets/readme/` for optimized public media and document how screenshots are regenerated.
6. Introduce architecture decision records for model-provider contracts, graph semantics, generation stop conditions, and migrations.
7. Add `SUPPORT.md` with the boundary between GitHub Discussions, issues, security reports, and self-hosting troubleshooting.
8. Enable Discussions and seed `Show and tell`, `Models and providers`, and `Product architecture` categories.
9. Create beginner-sized, acceptance-tested issues and apply `good first issue` only when the contribution path is genuinely bounded.
10. Publish tagged releases with checksums and concise upgrade notes.

## Gaps exposed by the README

These are product or release gaps, not writing problems.

### Highest priority

- **The public identity is split.** The product is Strata, but the remote repository and clone URL are still `Spec_Forge`. This is the largest first-impression trust leak.
- **There is no real product media.** A repository claiming a visual, structured workflow needs a credible hero screenshot and short end-to-end loop.
- **The release is described as ready but remains a pre-release.** Publish a tagged `v0.1.0`, checksums, upgrade notes, and a verified clean-install transcript.
- **Provider guidance is compatibility-based, not quality-based.** Users need a maintained table of tested runtimes, model sizes, context requirements, workflow suitability, speed, and known limitations.
- **First-run cost is still high.** Docker starts Strata and PostgreSQL but assumes a separate model endpoint. A provider-preset path and one verified small local-model recipe would reduce abandonment.

### Product clarity

- **The layer vocabulary needs examples.** `Pillar`, `feature`, and `Capability Design Card` become clear inside the app, but one public example spanning all layers would teach the model faster than definitions.
- **Design-space coverage is the central promise but is not yet measurable to users.** Show which capability families were explored, what remains uncertain, why exploration stopped, and how a user can tell that a branch is broad enough without implying completeness.
- **The value of research needs a concrete before/after.** Show one decision changed by cited competitive evidence; otherwise the capability reads as another feature checkbox.
- **Manual-first behavior should be tested and demonstrated end to end.** It is a differentiator for teams that already know their domain and should not feel secondary to generation.
- **Export claims need sample artifacts.** Check representative Markdown, graph JSON, Capability Design JSON, and Spec Kit handoff files into `examples/` so users can judge interoperability before installing.

### Open-source readiness

- **The roadmap is not independently trackable.** Convert near-term items into milestones and issues with owners or acceptance criteria.
- **Contribution entry points are broad.** Add fixtures, design notes, and a small set of bounded issues so a new contributor can make a useful change without learning the entire layer model.
- **Security posture is private-network only.** If trusted-team deployment is important, provide an authenticated reverse-proxy example and threat-model notes.
- **Release evidence is fragmented across audit documents.** Summarize supported platforms and tested install paths in each release rather than asking users to reconstruct confidence from internal QA logs.

## Launch sequence

1. Rename the repository and repair every public URL.
2. Create one sanitized example project and export bundle.
3. Capture the hero screenshot and three product loops from that fixture.
4. Add media to the existing README slots and compress it.
5. Publish provider compatibility guidance.
6. Run a clean Docker install on a fresh host and record the evidence.
7. Tag `v0.1.0`, publish checksums and upgrade notes, then update the README status badge.
8. Enable Discussions and publish three tightly scoped starter issues.
9. Set the GitHub social preview and repository topics.
10. Announce only after every link, image, command, and clean-install step has been tested from the public repository.
