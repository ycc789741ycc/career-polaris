/** "just now", "5 min ago", "3 hours ago", "6 days ago", then a date. Pure. */
export function ago(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  if (days < 14) return days === 1 ? "yesterday" : `${days} days ago`;
  return new Date(iso).toLocaleDateString();
}

/** How long ago a posting went up, from its day ("2026-09-30"): "today",
 * "yesterday", "4 days ago", "1 week ago", "3 weeks ago", then the day.
 * Pure. */
export function postedLabel(day: string, now: Date = new Date()): string {
  const [year, month, date] = day.split("-").map(Number);
  const posted = Date.UTC(year!, month! - 1, date!);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.max(0, Math.round((today - posted) / 86_400_000));
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return weeks === 1 ? "1 week ago" : `${weeks} weeks ago`;
  return dayLabel(`${day}T00:00:00`);
}

/** "26 Sep 2026", the prototype's date form. Pure. */
export function dayLabel(iso: string): string {
  const day = new Date(iso);
  return `${day.getDate()} ${MONTHS[day.getMonth()]} ${day.getFullYear()}`;
}

// Spelled out rather than left to the locale, which writes September "Sept".
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
