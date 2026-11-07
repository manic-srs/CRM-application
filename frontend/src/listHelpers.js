// Plain helpers for the list pages: paging text, applied-filter chips, selection wording and the actions offered for
// ticked leads. No React here, so the node test runner checks them directly (domain.test.js).

// Date ranges offered by the column filters. "past" fits created dates, "future" fits close and due dates.
export const PAST_RANGES = [
  ["today", "Today"],
  ["week", "This week"],
  ["last7", "Last 7 days"],
  ["last30", "Last 30 days"],
  ["month", "This month"],
  ["quarter", "This quarter"],
  ["year", "This year"],
];
export const FUTURE_RANGES = [
  ["overdue", "Before today"],
  ["today", "Today"],
  ["week", "This week"],
  ["next7", "Next 7 days"],
  ["next30", "Next 30 days"],
  ["month", "This month"],
  ["quarter", "This quarter"],
];
const RANGE_LABEL = Object.fromEntries([...PAST_RANGES, ...FUTURE_RANGES, ["custom", "Custom range"]]);

const number = (n) => Number(n).toLocaleString("en-US");

// "Lead Source: Upload", "Created: Last 7 days", "Account: contains "acme"" (the text under a list title)
export function filterText(def, values) {
  const v = values[def.key];
  const text =
    def.type === "text"
      ? `contains "${v}"`
      : def.type === "date"
        ? (def.ranges || []).find(([o]) => o === v)?.[1] || RANGE_LABEL[v]
        : def.options.find(([o]) => o === v)?.[1] || v;
  return `${def.label}: ${text}`;
}

const day = (s) => new Date(`${s}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

// The text on one applied-filter chip: like filterText, but a custom date range shows its dates
export function chipText(def, values) {
  const v = values[def.key];
  if (def.type === "date" && v === "custom") {
    const from = values[`${def.key}_from`];
    const to = values[`${def.key}_to`];
    if (from && to) return `${def.label}: ${day(from)} – ${day(to)}`;
    if (from) return `${def.label}: from ${day(from)}`;
    if (to) return `${def.label}: until ${day(to)}`;
  }
  return filterText(def, values);
}

// The filter values without one filter (a date filter's own from/to dates go with it)
export function withoutFilter(values, key) {
  const next = { ...values };
  delete next[key];
  delete next[`${key}_from`];
  delete next[`${key}_to`];
  return next;
}

// One chip per applied filter, in the order the filters are offered; `without` is what the values become when the
// chip is removed
export const filterChips = (defs, values) =>
  defs.filter((f) => values[f.key]).map((f) => ({ key: f.key, text: chipText(f, values), without: withoutFilter(values, f.key) }));

// "Showing 16–30 of 42 leads"; an empty list says so (never "1–0 of 0")
export function pageSummary({ start, size, total, noun = "item", nouns = `${noun}s` }) {
  if (!total) return `No ${nouns} to show`;
  const first = Math.min(Math.max(0, start), total - 1) + 1;
  const last = Math.min(first - 1 + size, total);
  return `Showing ${number(first)}–${number(last)} of ${number(total)} ${total === 1 ? noun : nouns}`;
}

// The page (0-based) to show once the total is known: a page past the end (after a delete, a transfer or a smaller
// page size) moves back to the last page
export const clampPage = (page, total, size) => Math.max(0, Math.min(page, Math.ceil(total / size) - 1));

// "Sorted by Created, newest first"
const DATE_SORTS = new Set(["created", "modified"]);
export function sortText(label, col, dir) {
  if (!label) return "";
  const way = DATE_SORTS.has(col) ? (dir === "asc" ? "oldest first" : "newest first") : dir === "asc" ? "A–Z" : "Z–A";
  return `Sorted by ${label}, ${way}`;
}

// How the ticked rows relate to the page on screen. "Select all" ticks only the rows on this page, and ticks stay
// when the page changes, so the bar says where the ticked rows are.
export function selectionSummary(selected, pageIds) {
  const count = selected.size;
  const onPage = pageIds.filter((id) => selected.has(id)).length;
  const elsewhere = count - onPage;
  let where = "";
  if (count) {
    if (!elsewhere) where = onPage === pageIds.length && onPage > 1 ? `All ${onPage} on this page` : "On this page";
    else if (!onPage) where = `${number(elsewhere)} on other pages`;
    else where = `${number(onPage)} on this page, ${number(elsewhere)} on other pages`;
  }
  return { count, onPage, elsewhere, where };
}

// Transfer and Delete run on up to this many leads at a time (the server's limit)
export const BULK_LIMIT = 500;

// The actions for the ticked leads, in the order shown. convertChoice comes from leadConvertChoice (domain.js):
// one open lead the user may convert opens the Convert popup; several ticked only explain; otherwise it is off with
// the reason. Email Campaign and Transfer are offered only to users with those rights; the server checks every lead.
export function leadSelectionActions({ count, convertChoice, canCampaign, canTransfer }) {
  if (!count) return [];
  const one = count === 1;
  const limit = count > BULK_LIMIT ? `Up to ${BULK_LIMIT} leads at a time` : undefined;
  return [
    {
      key: "convert",
      label: "Convert to Opportunity",
      disabled: !convertChoice.action && !convertChoice.explain,
      reason: convertChoice.reason,
    },
    canCampaign && { key: "campaign", label: "Email Campaign" },
    canTransfer && { key: "transfer", label: `Transfer ${one ? "Lead" : "Leads"}`, disabled: !!limit, reason: limit },
    { key: "delete", label: `Delete ${one ? "Lead" : "Leads"}`, danger: true, disabled: !!limit, reason: limit },
  ].filter(Boolean);
}

// What an empty Leads list says: nothing matches the search / filters, the list view is empty, or there are no leads
export function leadsEmptyMessage({ search, filtered, view, viewName }) {
  if (search || filtered)
    return {
      title: "No leads match your search or filters",
      text: "Try a different search, or remove a filter.",
      clear: true,
    };
  if (view === "all") return { title: "No leads yet", text: "Leads you add or upload appear here." };
  return { title: `No leads in ${viewName || "this list view"}`, text: "Choose another list view to see other leads." };
}
