// Indian formats, everywhere. ₹1,12,500 — never ₹112,500. DD-MM-YYYY — never ISO.

export function inr(amount, { paise = false } = {}) {
  const value = Math.round(Number(amount) || 0);
  const sign = value < 0 ? "-" : "";
  const digits = String(Math.abs(value));
  if (digits.length <= 3) return `${sign}₹${digits}${paise ? ".00" : ""}`;
  const tail = digits.slice(-3);
  let head = digits.slice(0, -3);
  const groups = [];
  while (head.length > 2) {
    groups.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) groups.unshift(head);
  return `${sign}₹${groups.join(",")},${tail}`;
}

// The counter and the tax invoice are the only places that show paise. The
// books are integers of rupees, so `inr` stays the default everywhere else —
// but a GST split of 97.35 + 97.34 must not display as 97 + 97.
export function inrPaise(amount) {
  const value = Number(amount) || 0;
  const sign = value < 0 ? "-" : "";
  const fixed = Math.abs(value).toFixed(2);
  const [whole, decimals] = fixed.split(".");
  return `${sign}${inr(whole)}.${decimals}`;
}

export function shortInr(amount) {
  const value = Math.round(Number(amount) || 0);
  if (Math.abs(value) >= 10000000) return `₹${(value / 10000000).toFixed(1)}Cr`;
  if (Math.abs(value) >= 100000) return `₹${(value / 100000).toFixed(1)}L`;
  return inr(value);
}

export function ddmmyyyy(value) {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${date.getFullYear()}`;
}

export function timeOfDay(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

export function ago(value) {
  if (!value) return "";
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return ddmmyyyy(value);
}

export function monthName(period) {
  if (!period) return "";
  const [year, month] = period.split("-");
  const names = ["January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December"];
  return `${names[Number(month) - 1] ?? period} ${year}`;
}

export const pct = (value) => `${Math.round(Number(value) || 0)}%`;
