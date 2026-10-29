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

// Tables: 10/28/26, 7:11 PM (keeps date columns narrow)
export function shortDateTime(value) {
  if (!value) return "";
  return asDate(value).toLocaleString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "2-digit",
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

// "+91 98200 00110", "+1 416-555-0114", "4165550114" -> one consistent style with single spaces
export function formatPhone(value) {
  if (!value) return "";
  const text = String(value).trim();
  const digits = text.replace(/\D/g, "");
  if (!text.startsWith("+") && digits.length === 10) return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  if (text.startsWith("+1") && digits.length === 11) return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  if (text.startsWith("+91") && digits.length === 12) return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`;
  return text.replace(/[\s\-.()]+/g, " ").replace(/\s+/g, " ");
}

// Lists show only the start of a phone number; the full number is on the record page.
// "+1 (416) 555-0114" -> "+1 (416) •••-••••", "+91 98200 00110" -> "+91 982•• •••••"
export function maskPhone(value) {
  const text = formatPhone(value);
  if (!text) return "";
  const country = text.startsWith("+") ? (text.match(/^\+(\d{1,3})/)?.[1].length ?? 0) : 0;
  let shown = 0;
  const keep = country + 3; // country code + first 3 digits
  return text.replace(/\d/g, (d) => (++shown <= keep ? d : "•"));
}
