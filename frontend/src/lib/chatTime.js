/**
 * Chat timestamp formatting utility for WavyGo Connect.
 *
 * Replaces relative "x mins ago" with fixed, deterministic timestamps.
 * All inputs must be ISO 8601 strings (stored in UTC, displayed in local TZ).
 *
 * Set USE_24H = true for 24-hour clock; false for 12-hour (AM/PM).
 */

const USE_24H = true;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pad(n) { return String(n).padStart(2, "0"); }

const SHORT_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const FULL_DAYS  = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function formatTime(d) {
  if (USE_24H) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  let h = d.getHours();
  const m = pad(d.getMinutes());
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h}:${m} ${ampm}`;
}

function startOfDay(d) {
  const s = new Date(d);
  s.setHours(0, 0, 0, 0);
  return s;
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Format a chat message timestamp for inline display.
 *
 * - Today           →  "16:45"  or  "4:45 PM"
 * - Yesterday       →  "Yesterday, 16:45"
 * - Earlier this week →  "Mon, 16:45"
 * - Older (same year) →  "12 Mar, 16:45"
 * - Different year   →  "12 Mar 2025, 16:45"
 */
export function formatChatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const now = new Date();
    const todayStart = startOfDay(now);
    const msgDay = startOfDay(d);
    const time = formatTime(d);

    const diffDays = Math.round((todayStart - msgDay) / 86400000);

    if (diffDays === 0) return time;
    if (diffDays === 1) return `Yesterday, ${time}`;
    if (diffDays >= 2 && diffDays <= 6) return `${SHORT_DAYS[d.getDay()]}, ${time}`;

    const day = d.getDate();
    const month = SHORT_MONTHS[d.getMonth()];
    if (d.getFullYear() === now.getFullYear()) return `${day} ${month}, ${time}`;
    return `${day} ${month} ${d.getFullYear()}, ${time}`;
  } catch {
    return "";
  }
}

/**
 * Full date-time for tooltip (hover / long-press).
 * e.g. "Saturday, 3 Oct 2026, 16:45"  or  "Saturday, 3 Oct 2026, 4:45 PM"
 */
export function formatChatTimeFull(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return `${FULL_DAYS[d.getDay()]}, ${d.getDate()} ${SHORT_MONTHS[d.getMonth()]} ${d.getFullYear()}, ${formatTime(d)}`;
  } catch {
    return "";
  }
}

/**
 * Date separator label for grouping messages by day inside a conversation.
 *
 * - Today       →  "Today"
 * - Yesterday   →  "Yesterday"
 * - Same year   →  "12 Mar"
 * - Other year  →  "12 Mar 2025"
 */
export function formatDateSeparator(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const now = new Date();
    const todayStart = startOfDay(now);
    const msgDay = startOfDay(d);
    const diffDays = Math.round((todayStart - msgDay) / 86400000);

    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    const day = d.getDate();
    const month = SHORT_MONTHS[d.getMonth()];
    if (d.getFullYear() === now.getFullYear()) return `${day} ${month}`;
    return `${day} ${month} ${d.getFullYear()}`;
  } catch {
    return "";
  }
}
