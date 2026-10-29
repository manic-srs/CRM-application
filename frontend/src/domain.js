export const LEAD_STAGES = ["New", "Nurturing", "Demo", "Converted", "Lost"];
export const OPPORTUNITY_STAGES = ["Opportunity", "Proposal", "Won", "Lost"];
export const LEAD_SOURCES = [
  "Website",
  "Referral",
  "Phone",
  "Email",
  "Event",
  "Social Media",
  "Other",
];
// leads created by a bulk upload (not offered on the New Lead form)
export const UPLOAD_SOURCE = "Upload";
export const LOST_REASONS = [
  "Price",
  "Competitor",
  "No response",
  "No budget",
  "Not interested",
  "Other",
];
export const SALUTATIONS = ["Mr.", "Ms.", "Mrs.", "Dr.", "Prof."];
export const PRIORITIES = ["Low", "Normal", "High"];
export const dateKey = (date = new Date()) =>
  new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
// The current backend stores amounts without a currency field.
export const money = (value) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(
        value,
      );
export const localInput = (value) => (value ? value.slice(0, 16) : "");
export function salesOverview(data) {
  const home = data.home;
  const result = (outcome) =>
    home?.won_vs_lost?.find((item) => item.outcome === outcome);
  const wonCount = result("Won")?.deals || 0,
    lostCount = result("Lost")?.deals || 0;
  return {
    totalLeads: home?.summary?.total_leads || 0,
    openOpportunities: home?.summary?.open_opportunities || 0,
    wonCount,
    lostCount,
    wonValue: result("Won")?.value,
    lostValue: result("Lost")?.value,
    stages: (
      home?.pipeline ||
      [
        "New",
        "Nurturing",
        "Demo",
        "Opportunity",
        "Proposal",
        "Won",
        "Lost",
      ].map((stage) => ({ stage, total: 0 }))
    ).map((item) => ({ stage: item.stage, count: item.total })),
    activeCount: (home?.pipeline || [])
      .filter((item) => !["Won", "Lost"].includes(item.stage))
      .reduce((sum, item) => sum + item.total, 0),
    todayTasks: (home?.todays_tasks || [])
      .map((task) => data.tasks.find((item) => item.id === String(task.id)))
      .filter(Boolean),
    dueToday: home?.summary?.tasks_due_today || 0,
    winRate:
      wonCount + lostCount
        ? Math.round((wonCount / (wonCount + lostCount)) * 100)
        : 0,
  };
}
