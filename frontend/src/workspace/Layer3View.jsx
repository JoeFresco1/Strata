import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import ColumnHeader from "./ColumnHeader";
import { approvedLayer2Features } from "./workspaceSelectors";
import WorkspacePageLayout, { WorkspaceActionButton, WorkspaceActionGroup, WorkspaceStatusBadge } from "./WorkspacePage";
import WorkspaceJobNotice from "./WorkspaceJobNotice";

const CONFIGURATION_KINDS = ["boolean", "single_select", "multi_select", "numeric", "text", "rule", "workflow", "content", "integration", "other"];
const SELECTION_STATES = ["undecided", "include", "exclude"];

function decisionLabel(value) {
  if (value === "include") return "Kept";
  if (value === "exclude") return "Rejected";
  if (value === "undecided") return "Needs review";
  return value;
}

function splitLines(value) {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinLines(value) {
  return (value || []).join("\n");
}

function makeId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptyGroup() {
  return {
    id: makeId("group"),
    name: "New subfeature group",
    description: "",
    options: [],
  };
}

function emptyOption() {
  return {
    id: makeId("option"),
    name: "New subfeature option",
    description: "",
    selection_state: "undecided",
    configuration_kind: "other",
    default_recommendation: "",
    rationale: "",
    dependencies: [],
    overlaps_feature_ids: [],
  };
}

function normalizeExpansion(expansion) {
  return {
    feature_intent: expansion?.feature_intent || "",
    expansion_groups: (expansion?.expansion_groups || []).map((group) => ({
      id: group.id || makeId("group"),
      name: group.name || "Subfeature group",
      description: group.description || "",
      options: (group.options || []).map((option) => ({
        id: option.id || makeId("option"),
        name: option.name || "Subfeature option",
        description: option.description || "",
        selection_state: option.selection_state || "undecided",
        configuration_kind: option.configuration_kind || "other",
        default_recommendation: option.default_recommendation || "",
        rationale: option.rationale || "",
        dependencies: option.dependencies || [],
        overlaps_feature_ids: option.overlaps_feature_ids || [],
      })),
    })),
    overlap_review: expansion?.overlap_review || [],
    open_questions: expansion?.open_questions || [],
  };
}

function optionCounts(expansion) {
  const options = (expansion?.expansion_groups || []).flatMap((group) => group.options || []);
  return {
    total: options.length,
    include: options.filter((option) => option.selection_state === "include").length,
    exclude: options.filter((option) => option.selection_state === "exclude").length,
    undecided: options.filter((option) => option.selection_state === "undecided").length,
  };
}

function overlapText(item) {
  if (typeof item === "string") return item;
  return [item.feature_id, item.summary, item.recommendation].filter(Boolean).join(" | ");
}

function compareValues(left, right, direction) {
  const leftMissing = left === null || left === undefined || left === "";
  const rightMissing = right === null || right === undefined || right === "";
  if (leftMissing && rightMissing) return 0;
  if (leftMissing) return 1;
  if (rightMissing) return -1;
  const result = typeof left === "number" && typeof right === "number"
    ? left - right
    : String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
  return direction === "asc" ? result : -result;
}

export default function Layer3View({
  snapshot,
  workspaceState,
  onGenerate,
  onUpdateExpansion,
  onReviewExpansion,
  onExportLayer3,
  onResearch,
  generationJobState,
  researchJobState,
  onCancelJob,
}) {
  const approvedFeatures = approvedLayer2Features(snapshot);
  const expansions = snapshot?.layer3?.expansions || [];
  const expansionByFeatureId = useMemo(() => Object.fromEntries(expansions.map((expansion) => [expansion.feature_id, expansion])), [expansions]);
  const pillars = (snapshot?.nodes || []).filter((node) => node.layer === 1 && node.node_type === "pillar");
  const pillarById = useMemo(() => Object.fromEntries(pillars.map((pillar) => [pillar.id, pillar])), [pillars]);
  const [expandedFeatureId, setExpandedFeatureId] = useState("");
  const [selectedFeatureIds, setSelectedFeatureIds] = useState([]);
  const [selectedOptionKeys, setSelectedOptionKeys] = useState([]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ pillar: "all", status: "all" });
  const [sortConfig, setSortConfig] = useState({ key: "pillar", direction: "asc" });
  const [draft, setDraft] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [overlapDraft, setOverlapDraft] = useState("");
  const lastWorkspaceSelection = useRef("");

  const expandedFeature = approvedFeatures.find((feature) => feature.id === expandedFeatureId) || approvedFeatures[0] || null;
  const expandedExpansion = expandedFeature ? expansionByFeatureId[expandedFeature.id] : null;
  const generationRunning = generationJobState?.state === "running";
  const researchRunning = researchJobState?.state === "running";
  const missingExpansionFeatureIds = approvedFeatures.filter((feature) => !expansionByFeatureId[feature.id]).map((feature) => feature.id);
  const approvedExpansionCount = expansions.filter((expansion) => expansion.review_state === "approved").length;
  const visibleFeatures = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = approvedFeatures.filter((feature) => {
      const expansion = expansionByFeatureId[feature.id];
      const pillar = pillarById[feature.owner_pillar_id];
      const text = [feature.canonical_name, feature.description, pillar?.title, expansion?.review_state]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return (
        (!normalizedQuery || text.includes(normalizedQuery)) &&
        (filters.pillar === "all" || feature.owner_pillar_id === filters.pillar) &&
        (filters.status === "all" || (expansion?.review_state || "not_generated") === filters.status)
      );
    });
    return [...filtered].sort((left, right) => {
      const leftExpansion = expansionByFeatureId[left.id];
      const rightExpansion = expansionByFeatureId[right.id];
      const selectors = {
        name: (feature) => feature.canonical_name,
        pillar: (feature) => pillarById[feature.owner_pillar_id]?.title || "Unassigned",
        status: (feature) => expansionByFeatureId[feature.id]?.review_state || "not_generated",
        subfeatures: (feature) => optionCounts(expansionByFeatureId[feature.id]).total,
        include: (feature) => optionCounts(expansionByFeatureId[feature.id]).include,
        exclude: (feature) => optionCounts(expansionByFeatureId[feature.id]).exclude,
        undecided: (feature) => optionCounts(expansionByFeatureId[feature.id]).undecided,
      };
      const select = selectors[sortConfig.key] || selectors.pillar;
      return compareValues(select(left), select(right), sortConfig.direction) || left.canonical_name.localeCompare(right.canonical_name);
    });
  }, [approvedFeatures, expansionByFeatureId, filters, pillarById, query, sortConfig]);

  useEffect(() => {
    if (workspaceState?.selected_entity_type === "expansion" && workspaceState.selected_entity_id) {
      if (lastWorkspaceSelection.current === workspaceState.selected_entity_id) return;
      const expansion = expansions.find((item) => item.id === workspaceState.selected_entity_id);
      if (expansion && approvedFeatures.some((feature) => feature.id === expansion.feature_id)) {
        lastWorkspaceSelection.current = workspaceState.selected_entity_id;
        setExpandedFeatureId(expansion.feature_id);
        return;
      }
    }
    if (!expandedFeatureId && approvedFeatures[0]) {
      setExpandedFeatureId(approvedFeatures[0].id);
    }
    if (expandedFeatureId && !approvedFeatures.some((feature) => feature.id === expandedFeatureId)) {
      setExpandedFeatureId(approvedFeatures[0]?.id || "");
    }
  }, [approvedFeatures, expandedFeatureId, expansions, workspaceState?.selected_entity_id, workspaceState?.selected_entity_type]);

  useEffect(() => {
    if (!expandedExpansion) {
      setDraft(null);
      setOverlapDraft("");
      setDirty(false);
      return;
    }
    const nextDraft = normalizeExpansion(expandedExpansion);
    setDraft(nextDraft);
    setOverlapDraft(JSON.stringify(nextDraft.overlap_review, null, 2));
    setDirty(false);
  }, [expandedExpansion?.id, expandedExpansion?.updated_at]);

  function expandFeature(featureId) {
    if (dirty && !window.confirm("Discard unsaved Layer 3 edits?")) return;
    setExpandedFeatureId((current) => current === featureId ? "" : featureId);
    setSelectedOptionKeys([]);
  }

  function updateDraft(updater) {
    setDraft((current) => (typeof updater === "function" ? updater(current) : updater));
    setDirty(true);
  }

  function updateGroup(groupIndex, updates) {
    updateDraft((current) => ({
      ...current,
      expansion_groups: current.expansion_groups.map((group, index) => (
        index === groupIndex ? { ...group, ...updates } : group
      )),
    }));
  }

  function updateOption(groupIndex, optionIndex, updates) {
    updateDraft((current) => ({
      ...current,
      expansion_groups: current.expansion_groups.map((group, index) => (
        index === groupIndex
          ? {
            ...group,
            options: group.options.map((option, innerIndex) => (
              innerIndex === optionIndex ? { ...option, ...updates } : option
            )),
          }
          : group
      )),
    }));
  }

  function toggleFeatureSelection(featureId) {
    setSelectedFeatureIds((current) => current.includes(featureId) ? current.filter((id) => id !== featureId) : [...current, featureId]);
  }

  function toggleVisibleFeatures() {
    const visibleIds = visibleFeatures.map((feature) => feature.id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedFeatureIds.includes(id));
    setSelectedFeatureIds((current) => allVisibleSelected ? current.filter((id) => !visibleIds.includes(id)) : Array.from(new Set([...current, ...visibleIds])));
  }

  function toggleSort(key) {
    setSortConfig((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  }

  function optionKey(groupIndex, optionIndex) {
    return `${groupIndex}:${optionIndex}`;
  }

  function toggleOptionSelection(key) {
    setSelectedOptionKeys((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key]);
  }

  function setSelectedOptions(selectionState) {
    if (!selectedOptionKeys.length) return;
    updateDraft((current) => ({
      ...current,
      expansion_groups: current.expansion_groups.map((group, groupIndex) => ({
        ...group,
        options: group.options.map((option, optionIndex) => (
          selectedOptionKeys.includes(optionKey(groupIndex, optionIndex)) ? { ...option, selection_state: selectionState } : option
        )),
      })),
    }));
    setSelectedOptionKeys([]);
  }

  async function saveDraft() {
    if (!expandedExpansion || !draft) return;
    let parsedOverlap = [];
    try {
      parsedOverlap = overlapDraft.trim() ? JSON.parse(overlapDraft) : [];
      if (!Array.isArray(parsedOverlap)) throw new Error("Overlap review must be a JSON array.");
    } catch (parseError) {
      window.alert(parseError.message);
      return;
    }
    await onUpdateExpansion(expandedExpansion.id, {
      feature_intent: draft.feature_intent,
      expansion_groups: draft.expansion_groups,
      overlap_review: parsedOverlap,
      open_questions: draft.open_questions,
    });
    setDirty(false);
  }

  async function generateMissing() {
    await onGenerate(missingExpansionFeatureIds.length ? missingExpansionFeatureIds : approvedFeatures.map((feature) => feature.id));
  }

  async function researchSelected() {
    await onResearch?.(selectedFeatureIds);
  }

  return (
    <WorkspacePageLayout
      id="workspace-panel-layer3"
      ariaLabel="Layer 3 feature expansions"
      title="Sub-features"
      description="Expand approved features into editable sub-features, choices, validation rules, and open questions."
      status={!approvedFeatures.length ? "draft" : approvedExpansionCount ? "approved" : "needs_review"}
      primaryAction={(
        <WorkspaceActionButton
          primary
          onClick={selectedFeatureIds.length ? () => onGenerate(selectedFeatureIds) : generateMissing}
          disabled={generationRunning || !approvedFeatures.length}
          disabledReason={generationRunning ? "Layer 3 generation is already running." : !approvedFeatures.length ? "Approve Layer 2 features first." : ""}
        >
          {selectedFeatureIds.length ? "Generate selected" : "Generate all"}
        </WorkspaceActionButton>
      )}
      actions={(
        <>
          <WorkspaceActionGroup label="Generate">
            <WorkspaceActionButton
              secondary
              onClick={generateMissing}
              disabled={generationRunning || !approvedFeatures.length}
              disabledReason={generationRunning ? "Layer 3 generation is already running." : !approvedFeatures.length ? "Approve Layer 2 features first." : ""}
            >
              Generate all
            </WorkspaceActionButton>
            <WorkspaceActionButton
              secondary
              onClick={() => onGenerate(selectedFeatureIds)}
              disabled={!selectedFeatureIds.length || generationRunning}
              disabledReason={!selectedFeatureIds.length ? "Select feature rows first." : generationRunning ? "Layer 3 generation is already running." : ""}
            >
              Generate selected
            </WorkspaceActionButton>
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Research">
            <WorkspaceActionButton
              secondary
              onClick={researchSelected}
              disabled={!selectedFeatureIds.length || researchRunning}
              disabledReason={!selectedFeatureIds.length ? "Select feature rows first." : researchRunning ? "Feature research is already running." : ""}
            >
              Research selected
            </WorkspaceActionButton>
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Review / Critique">
            <WorkspaceActionButton secondary onClick={onExportLayer3} disabled={!approvedExpansionCount} disabledReason={!approvedExpansionCount ? "Approve at least one expansion before export." : ""}>
              Export
            </WorkspaceActionButton>
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Selection actions">
            <WorkspaceActionButton secondary onClick={toggleVisibleFeatures} disabled={!visibleFeatures.length} disabledReason={!visibleFeatures.length ? "No visible rows to select." : ""}>Select all</WorkspaceActionButton>
            <span className="workspace-selection-count" aria-live="polite">{selectedFeatureIds.length ? `${selectedFeatureIds.length} selected` : `${visibleFeatures.length} of ${approvedFeatures.length} rows`}</span>
          </WorkspaceActionGroup>
        </>
      )}
      filters={approvedFeatures.length ? (
        <>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search sub-features" aria-label="Search Layer 3 rows" />
          <select value={filters.pillar} onChange={(event) => setFilters({ ...filters, pillar: event.target.value })} aria-label="Filter Layer 3 rows by pillar">
            <option value="all">All pillars</option>
            {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.title}</option>)}
          </select>
          <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })} aria-label="Filter Layer 3 rows by status">
            <option value="all">All statuses</option>
            <option value="not_generated">Draft</option>
            <option value="draft">Draft</option>
            <option value="needs_review">Needs review</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
          <label>
            Sort by
            <select value={sortConfig.key} onChange={(event) => setSortConfig({ ...sortConfig, key: event.target.value })} aria-label="Sort sub-features">
              <option value="pillar">Pillar</option>
              <option value="name">Feature</option>
              <option value="status">Status</option>
              <option value="subfeatures">Sub-features</option>
              <option value="include">Kept</option>
              <option value="exclude">Rejected</option>
              <option value="undecided">Needs review</option>
            </select>
          </label>
          <WorkspaceActionButton secondary onClick={() => setSortConfig((current) => ({ ...current, direction: current.direction === "asc" ? "desc" : "asc" }))}>
            {sortConfig.direction === "asc" ? "Ascending" : "Descending"}
          </WorkspaceActionButton>
        </>
      ) : null}
    >

      <WorkspaceJobNotice jobState={generationJobState} label="Layer 3 generation" onCancel={onCancelJob} />
      <WorkspaceJobNotice jobState={researchJobState} label="Layer 2 feature research" onCancel={onCancelJob} />
      {generationJobState?.state === "failed" ? <div className="warning">Layer 3 generation failed. Check Analytics for details.</div> : null}

      {approvedFeatures.length ? (
        <>
        <div className="workspace-table-wrap layer3-table-wrap">
          <table className="workspace-review-table layer3-review-table">
            <thead>
              <tr>
                <th scope="col"><ColumnHeader label="Select" description="Choose one or more Layer 2 feature rows for batch research or generation." /></th>
                <th scope="col"><ColumnHeader label="Open" description="Expand the row to review and edit generated Layer 3 subfeatures." /></th>
                <th scope="col"><ColumnHeader label="Layer 2 feature" description="The approved Layer 2 feature being expanded one level deeper." sortKey="name" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Pillar" description="The Layer 1 pillar that owns this feature." sortKey="pillar" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Status" description="Layer 3 expansion review state." sortKey="status" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Sub-features" description="Total generated Layer 3 subfeature/options." sortKey="subfeatures" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Kept" description="Subfeature rows marked to keep." sortKey="include" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Rejected" description="Subfeature rows marked rejected." sortKey="exclude" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Needs review" description="Subfeature rows still undecided." sortKey="undecided" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Actions" description="Row-level generation, research, and expansion controls." /></th>
              </tr>
            </thead>
            <tbody>
              {visibleFeatures.map((feature) => {
                const expansion = expansionByFeatureId[feature.id];
                const counts = optionCounts(expansion);
                const expanded = expandedFeatureId === feature.id;
                const pillar = pillarById[feature.owner_pillar_id];
                return (
                  <Fragment key={feature.id}>
                    <tr key={feature.id} className={expanded ? "layer3-parent-row expanded" : "layer3-parent-row"}>
                      <td><input type="checkbox" checked={selectedFeatureIds.includes(feature.id)} onChange={() => toggleFeatureSelection(feature.id)} aria-label={`Select ${feature.canonical_name}`} /></td>
                      <td>
                        <button type="button" className="secondary-button layer3-expand-button" onClick={() => expandFeature(feature.id)} aria-expanded={expanded} aria-label={`${expanded ? "Collapse" : "Expand"} ${feature.canonical_name}`}>
                          {expanded ? "Collapse" : "Expand"}
                        </button>
                      </td>
                      <td>
                        <strong>{feature.canonical_name}</strong>
                        <p className="muted">{feature.description || "No Layer 2 description yet."}</p>
                      </td>
                      <td>{pillar?.title || "Unassigned"}</td>
                      <td><WorkspaceStatusBadge status={expansion?.review_state || "not_generated"} /></td>
                      <td>{counts.total || "-"}</td>
                      <td>{counts.include || "-"}</td>
                      <td>{counts.exclude || "-"}</td>
                      <td>{counts.undecided || "-"}</td>
                      <td>
                        <div className="button-row">
                          <button type="button" className="secondary-button" onClick={() => onGenerate([feature.id])} disabled={generationRunning}>
                            Generate row
                          </button>
                          <button type="button" className="secondary-button" onClick={() => onResearch?.([feature.id])} disabled={researchRunning} title={researchRunning ? "Feature research is already running." : "Research this row"}>Research row</button>
                        </div>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr key={`${feature.id}-detail`} className="layer3-expanded-row">
                        <td colSpan={10}>
                          {expansion && draft ? (
                            <div className="layer3-expanded-panel">
                              <div className="workspace-section-heading">
                                <label>
                                  Feature intent
                                  <textarea value={draft.feature_intent} onChange={(event) => updateDraft({ ...draft, feature_intent: event.target.value })} rows={3} />
                                </label>
                                <div className="button-row">
                                  <button type="button" className="secondary-button" onClick={saveDraft} disabled={!dirty}>Save edits</button>
                                  <button type="button" className="secondary-button" onClick={() => onReviewExpansion(expansion.id, "approve")} disabled={dirty}>Approve expansion</button>
                                  <button type="button" className="secondary-button" onClick={() => onReviewExpansion(expansion.id, "needs_review")} disabled={dirty}>Needs review</button>
                                  <button type="button" className="secondary-button danger-button" onClick={() => onReviewExpansion(expansion.id, "reject")} disabled={dirty}>Reject expansion</button>
                                </div>
                              </div>
                              {dirty ? <p className="warning">Save edits before approving or exporting this expansion.</p> : null}

                              <div className="button-row">
                                <button type="button" className="secondary-button" onClick={() => updateDraft({ ...draft, expansion_groups: [...draft.expansion_groups, emptyGroup()] })}>Add subfeature group</button>
                                <button type="button" className="secondary-button" onClick={() => setSelectedOptions("include")} disabled={!selectedOptionKeys.length}>Keep selected</button>
                                <button type="button" className="secondary-button" onClick={() => setSelectedOptions("exclude")} disabled={!selectedOptionKeys.length}>Reject selected</button>
                                <button type="button" className="secondary-button" onClick={() => setSelectedOptions("undecided")} disabled={!selectedOptionKeys.length}>Review selected</button>
                              </div>

                              {draft.expansion_groups.map((group, groupIndex) => (
                                <section className="layer3-subtable-section" key={group.id || groupIndex}>
                                  <div className="layer3-group-head">
                                    <input value={group.name} onChange={(event) => updateGroup(groupIndex, { name: event.target.value })} aria-label="Subfeature group name" />
                                    <button type="button" className="secondary-button" onClick={() => updateDraft({ ...draft, expansion_groups: draft.expansion_groups.filter((_, index) => index !== groupIndex) })}>Remove group</button>
                                  </div>
                                  <textarea value={group.description} onChange={(event) => updateGroup(groupIndex, { description: event.target.value })} rows={2} aria-label={`${group.name} description`} />
                                  <div className="workspace-table-wrap">
                                    <table className="workspace-review-table layer3-subfeature-table">
                                      <thead>
                                        <tr>
                                          <th scope="col"><ColumnHeader label="Subfeature / choice" description="Editable Layer 3 option name, description, and rationale." /></th>
                                          <th scope="col"><ColumnHeader label="Select" description="Choose subfeature rows for batch keep, reject, or review decisions." /></th>
                                          <th scope="col"><ColumnHeader label="Decision" description="Whether this subfeature should be included, excluded, or left for review." /></th>
                                          <th scope="col"><ColumnHeader label="Kind" description="The configuration or product-choice category for this subfeature." /></th>
                                          <th scope="col"><ColumnHeader label="Dependencies" description="Other capabilities or choices this subfeature depends on." /></th>
                                          <th scope="col"><ColumnHeader label="Overlap IDs" description="Related feature IDs that may overlap or need coordination." /></th>
                                          <th scope="col"><ColumnHeader label="Actions" description="Row-level controls for quickly setting or removing this subfeature." /></th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {group.options.map((option, optionIndex) => (
                                          <tr key={option.id || optionIndex}>
                                            <td>
                                              <input value={option.name} onChange={(event) => updateOption(groupIndex, optionIndex, { name: event.target.value })} aria-label="Subfeature option name" />
                                              <textarea value={option.description} onChange={(event) => updateOption(groupIndex, optionIndex, { description: event.target.value })} rows={2} aria-label={`${option.name} description`} />
                                              <textarea value={option.rationale} onChange={(event) => updateOption(groupIndex, optionIndex, { rationale: event.target.value })} rows={2} aria-label={`${option.name} rationale`} placeholder="Rationale / check notes" />
                                            </td>
                                            <td><input type="checkbox" checked={selectedOptionKeys.includes(optionKey(groupIndex, optionIndex))} onChange={() => toggleOptionSelection(optionKey(groupIndex, optionIndex))} aria-label={`Select ${option.name}`} /></td>
                                            <td>
                                              <select value={option.selection_state} onChange={(event) => updateOption(groupIndex, optionIndex, { selection_state: event.target.value })} aria-label="Decision">
                                                {SELECTION_STATES.map((state) => <option key={state} value={state}>{decisionLabel(state)}</option>)}
                                              </select>
                                            </td>
                                            <td>
                                              <select value={option.configuration_kind} onChange={(event) => updateOption(groupIndex, optionIndex, { configuration_kind: event.target.value })} aria-label="Configuration kind">
                                                {CONFIGURATION_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
                                              </select>
                                            </td>
                                            <td>
                                              <input value={(option.dependencies || []).join(", ")} onChange={(event) => updateOption(groupIndex, optionIndex, { dependencies: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} aria-label="Dependencies" />
                                            </td>
                                            <td>
                                              <input value={(option.overlaps_feature_ids || []).join(", ")} onChange={(event) => updateOption(groupIndex, optionIndex, { overlaps_feature_ids: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} aria-label="Overlap feature IDs" />
                                            </td>
                                            <td>
                                              <div className="button-row">
                                                <button type="button" className="secondary-button" onClick={() => updateOption(groupIndex, optionIndex, { selection_state: "include" })}>Keep</button>
                                                <button type="button" className="secondary-button danger-button" onClick={() => updateOption(groupIndex, optionIndex, { selection_state: "exclude" })}>Reject</button>
                                                <button type="button" className="secondary-button" onClick={() => updateOption(groupIndex, optionIndex, { selection_state: "undecided" })}>Review</button>
                                                <button type="button" className="secondary-button" onClick={() => updateGroup(groupIndex, { options: group.options.filter((_, index) => index !== optionIndex) })}>Remove</button>
                                              </div>
                                            </td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                  <button type="button" className="secondary-button" onClick={() => updateGroup(groupIndex, { options: [...group.options, emptyOption()] })}>Add subfeature</button>
                                </section>
                              ))}

                              <div className="layer3-split">
                                <label>
                                  Open questions
                                  <textarea value={joinLines(draft.open_questions)} onChange={(event) => updateDraft({ ...draft, open_questions: splitLines(event.target.value) })} rows={6} />
                                </label>
                                <label>
                                  Overlap review JSON
                                  <textarea value={overlapDraft} onChange={(event) => { setOverlapDraft(event.target.value); setDirty(true); }} rows={6} />
                                </label>
                              </div>
                              {draft.overlap_review?.length ? (
                                <div className="workspace-chip-row">
                                  {draft.overlap_review.map((item, index) => <span key={`${overlapText(item)}-${index}`} className="workspace-chip">{overlapText(item)}</span>)}
                                </div>
                              ) : null}
                            </div>
                          ) : (
                            <div className="guided-empty-state">
                              <strong>No Layer 3 subfeatures generated yet.</strong>
                              <p className="muted">Generate this row to expand the approved Layer 2 feature into editable subfeatures and choices.</p>
                              <button type="button" className="secondary-button" onClick={() => onGenerate([feature.id])} disabled={generationRunning}>Generate row</button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        </>
      ) : (
        <div className="panel guided-empty-state">
          <strong>Layer 3 starts after Layer 2 approval.</strong>
          <p className="muted">Approve at least one Layer 2 feature, then return here to expand it into product-level subfeatures and choices.</p>
        </div>
      )}
    </WorkspacePageLayout>
  );
}
