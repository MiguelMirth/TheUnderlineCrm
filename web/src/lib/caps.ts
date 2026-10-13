// Labels for volume limits. Gather shows the per-run set. The Preset screen shows every key the API returns.
export const CAP_LABELS: Record<string, string> = {
  target: "Lead target",
  max_pages: "Apollo pages per title chunk",
  title_chunk: "Titles per search",
  org_pages: "Org search pages",
  events: "Events",
  brands: "Brands per run",
  queries_per_source: "Searches per source",
  tavily_batch: "Brands per sponsorship search",
  gemini_batch: "Rows per Gemini request",
};

export const RUN_CAP_KEYS = new Set([
  "target",
  "max_pages",
  "title_chunk",
  "org_pages",
  "events",
  "brands",
  "queries_per_source",
]);
