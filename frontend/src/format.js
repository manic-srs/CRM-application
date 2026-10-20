// Display helpers shared by the screens.

// 850000 -> "850K", 2550000 -> "2.55M". The backend has no currency field, so no symbol is added.
export function compact(value) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Math.abs(n) >= 1e6) return `${+(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `${+(n / 1e3).toFixed(1)}K`;
  return String(+n.toFixed(2));
}

export function amount(value) {
  if (value == null || value === "") return "";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(
    value,
  );
}

const asDate = (value) =>
  value.length === 10 ? new Date(`${value}T12:00:00`) : new Date(value);

export function shortDate(value) {
  if (!value) return "";
  return asDate(value).toLocaleDateString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "numeric",
  });
}

export function dateTime(value) {
  if (!value) return "";
  return asDate(value).toLocaleString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function time(value) {
  if (!value) return "";
  return asDate(value).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function greeting(date = new Date()) {
  const h = date.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export const firstName = (fullName = "") => fullName.split(" ")[0];

export const initials = (name = "") =>
  name
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
