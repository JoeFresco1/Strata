export const FEATURE_STATUSES = ["candidate", "kept", "cut", "merged", "renamed", "needs_review", "approved"];
export const GRANULARITY_CLASSES = ["feature", "feature_variant", "workflow", "rule", "configuration", "shared_concern", "too_broad", "too_low_level"];
export const COVERAGE_STATUSES = ["has_feature", "partial", "not_found", "unclear"];

function score(value) {
  return Number(value || 0);
}

export function sortFeatureRows(rows, sortKey) {
  const copy = [...rows];
  copy.sort((left, right) => {
    if (sortKey === "name") return left.canonical_name.localeCompare(right.canonical_name);
    if (sortKey === "status") return left.status.localeCompare(right.status);
    if (sortKey === "pillar_fit") return score(right.pillar_fit_score) - score(left.pillar_fit_score);
    if (sortKey === "strategic") return score(right.strategic_value_score) - score(left.strategic_value_score);
    if (sortKey === "research") return score(right.competitor_coverage_score) - score(left.competitor_coverage_score);
    return score(right.created_at) - score(left.created_at);
  });
  return copy;
}

export function featureMatchesFilters(row, filters) {
  const query = filters.query.trim().toLowerCase();
  const haystack = [row.canonical_name, row.description, row.feature_type, row.granularity_class, row.coverage_family, row.status]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return (
    (!query || haystack.includes(query)) &&
    (filters.pillar === "all" || row.owner_pillar_id === filters.pillar) &&
    (filters.status === "all" || row.status === filters.status) &&
    (filters.research === "all" || row.research_status === filters.research) &&
    (!filters.readyOnly || row.layer3_ready)
  );
}

export function splitLines(value) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}
