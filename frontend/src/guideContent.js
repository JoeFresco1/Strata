// Guide copy is manually maintained reference content, not derived from live
// runtime or schema state. Update this file deliberately when layer behavior
// or workflow expectations change.

export const GUIDE_FLOW_STEPS = [
  {
    label: "Library",
    title: "Choose the project",
    body: "Open active work, duplicate a useful starting point, archive old runs, or import a project archive.",
  },
  {
    label: "Tree",
    title: "Orient first",
    body: "Use the map to see the brief, pillars, and features together before drilling into a layer.",
  },
  {
    label: "Layer 0",
    title: "Lock the brief",
    body: "Shape the product idea, users, constraints, goals, and rejected directions, then publish the brief.",
  },
  {
    label: "Layer 1",
    title: "Review pillars",
    body: "Accept, reject, merge, rename, prioritize, or manually add the major product areas.",
  },
  {
    label: "Layer 2",
    title: "Approve features",
    body: "Generate or add feature candidates, review evidence, resolve weak items, and approve the set you want.",
  },
  {
    label: "Handoff",
    title: "Export",
    body: "Export the reviewed feature set, full project data, or a portable project archive.",
  },
];

export const GUIDE_DECISION_ROUTES = [
  {
    need: "The idea is still fuzzy",
    go: "Layer 0",
    action: "Use the brief workspace to tighten the idea, audience, constraints, goals, and known no-go directions.",
  },
  {
    need: "I need the product shape",
    go: "Tree",
    action: "Start from the tree view to see what exists, what is still empty, and where the next review belongs.",
  },
  {
    need: "I know the big areas already",
    go: "Layer 1",
    action: "Add or edit pillars directly, then accept the ones that should become feature families.",
  },
  {
    need: "I need concrete features",
    go: "Layer 2",
    action: "Generate from accepted pillars or add features manually, then approve, reject, or revise them.",
  },
  {
    need: "I need a file to share",
    go: "Export",
    action: "Use the handoff tab after Layer 2 review to create the full project, Layer 2, or archive export.",
  },
  {
    need: "Something is blocked",
    go: "Readiness",
    action: "Open Runtime Analytics or Project Settings to check jobs, provider readiness, model routing, and research setup.",
  },
];

export const GUIDE_UTILITY_ROUTES = [
  {
    title: "Project Settings",
    body: "Per-project compute mode, model routing, research behavior, exports, and diagnostics.",
  },
  {
    title: "App Settings",
    body: "Global defaults for new projects, runtime profiles, routing policy, and assignment maps.",
  },
  {
    title: "System Prompts",
    body: "Prompt catalog changes for future projects without rewriting current project snapshots.",
  },
  {
    title: "Assistant",
    body: "Grounded project questions, navigation help, durable conversations, and action proposals.",
  },
  {
    title: "Runtime Analytics",
    body: "Health, recent jobs, diagnostics, and provider readiness when generation or research needs checking.",
  },
];

export const GUIDE_OPERATIONAL_LAYERS = [
  {
    id: "layer0",
    eyebrow: "Layer 0",
    title: "Brief and publish",
    flow: ["Capture brief", "Refine", "Publish", "Unlock downstream"],
    description: "This is where the product idea becomes a usable brief with audience, constraints, goals, and known non-go directions.",
    agentDoes: "Supports conversational intake, preserves the canonical brief, and can run market-landscape research after the brief is ready.",
    userDoes: "Tightens the brief, checks whether the idea is coherent, and decides when the brief is ready to publish.",
    gateOutput: "Publishing Layer 0 freezes the current brief state and unlocks Layer 1.",
  },
  {
    id: "layer1",
    eyebrow: "Layer 1",
    title: "Shape the pillars",
    flow: ["Generate or add pillars", "Review", "Approve", "Establish product areas"],
    description: "This layer defines the major product areas that organize downstream feature work.",
    agentDoes: "Generates candidate pillars, preserves manual additions, and keeps the review set available for acceptance, rejection, merge, rename, and prioritization.",
    userDoes: "Curates the pillar set, removes weak areas, and approves the major product areas worth exploring further.",
    gateOutput: "Keeping approved pillars establishes the product areas that Layer 2 can expand into features.",
  },
  {
    id: "layer2",
    eyebrow: "Layer 2",
    title: "Review the feature set",
    flow: ["Generate features", "Gather evidence", "Review", "Approve set"],
    description: "This layer turns approved pillars into concrete features with supporting evidence and review decisions.",
    agentDoes: "Generates candidate features, stores evidence and research context, and keeps the workbench ready for review without turning weak ideas into approved work automatically.",
    userDoes: "Approves strong features, rejects or revises weak ones, and decides which features belong in the reviewed product set.",
    gateOutput: "Approved Layer 2 features become the reviewed feature set used for export and later capability design.",
  },
  {
    id: "layer3",
    eyebrow: "Layer 3",
    title: "Define capabilities",
    flow: ["Define capability", "Pressure test", "Review", "Approve or export"],
    description: "This layer turns approved features into broader capability definitions that are reviewed before handoff.",
    agentDoes: "Builds capability-design cards, runs pressure tests, and keeps review state tied to the latest card content.",
    userDoes: "Checks whether the capability definition is coherent, resolves review concerns, and decides when the card is ready to approve or export.",
    gateOutput: "A reviewed capability card is the Layer 3 handoff artifact for downstream definition and export work.",
  },
];
