import { FileText, FileImage, FileSpreadsheet, FileType2, Presentation, FileCode2, File as FileIcon } from "lucide-react";
import { api } from "@/lib/api";

export const MAX_BYTES = 25 * 1024 * 1024;
export const ALLOWED_EXT = ["pdf", "png", "jpg", "jpeg", "webp", "docx", "xlsx", "pptx", "csv", "txt"];
export const ACCEPT = ALLOWED_EXT.map((e) => `.${e}`).join(",");
export const PREVIEWABLE = new Set(["application/pdf", "image/png", "image/jpeg", "image/webp"]);

const TYPE_META = {
  "application/pdf": { icon: FileText, label: "PDF", tone: "text-destructive bg-destructive/10" },
  "image/png": { icon: FileImage, label: "PNG", tone: "text-info bg-info/10" },
  "image/jpeg": { icon: FileImage, label: "JPG", tone: "text-info bg-info/10" },
  "image/webp": { icon: FileImage, label: "WEBP", tone: "text-info bg-info/10" },
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": { icon: FileType2, label: "DOCX", tone: "text-primary bg-primary/10" },
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": { icon: FileSpreadsheet, label: "XLSX", tone: "text-success bg-success/10" },
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": { icon: Presentation, label: "PPTX", tone: "text-warning bg-warning/10" },
  "text/csv": { icon: FileCode2, label: "CSV", tone: "text-success bg-success/10" },
  "text/plain": { icon: FileText, label: "TXT", tone: "text-muted-foreground bg-muted" },
};

export function typeMeta(contentType) {
  return TYPE_META[contentType] || { icon: FileIcon, label: "FILE", tone: "text-muted-foreground bg-muted" };
}

export function formatBytes(n) {
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  const v = n / 1024 ** i;
  return `${i === 0 ? v : v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
}

export function formatDate(value) {
  if (!value) return "";
  // Date-only values (YYYY-MM-DD) are calendar dates, not instants; don't shift them by timezone.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Label + classes for a document's expiry badge, or null when it has no expiry. */
export function expiryBadge(doc) {
  const { expiry_status: status, days_to_expiry: days } = doc || {};
  if (!status) return null;
  if (status === "expired") {
    return { label: days === -1 ? "Expired yesterday" : `Expired ${Math.abs(days)}d ago`, className: "bg-destructive/10 text-destructive" };
  }
  if (status === "expiring") {
    return { label: days === 0 ? "Expires today" : `Expires in ${days}d`, className: "bg-warning/10 text-warning" };
  }
  return { label: `Expires ${formatDate(doc.expires_on)}`, className: "bg-muted text-foreground/70" };
}

export function extOf(name) {
  const i = (name || "").lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

/** Client-side pre-check; the server re-validates type, magic bytes and size. */
export function validateFile(file) {
  if (!file) return "Choose a file";
  if (!ALLOWED_EXT.includes(extOf(file.name))) return "Unsupported type. Allowed: PDF, PNG, JPG, WEBP, DOCX, XLSX, PPTX, CSV, TXT";
  if (file.size === 0) return "File is empty";
  if (file.size > MAX_BYTES) return "File is larger than 25 MB";
  return null;
}

export function parseTags(text) {
  const out = [];
  (text || "").split(",").forEach((t) => {
    const v = t.trim().replace(/\s+/g, " ").toLowerCase();
    if (v && !out.includes(v)) out.push(v);
  });
  return out;
}

function versionPath(docId, version) {
  return version ? `/vault/documents/${docId}/versions/${version}/download` : `/vault/documents/${docId}/download`;
}

/** Fetch a file through the authenticated axios client (tokens never go in URLs). */
export async function fetchBlob(docId, { version, inline = false, signal } = {}) {
  const { data } = await api.get(versionPath(docId, version), {
    params: inline ? { inline: true } : undefined,
    responseType: "blob",
    signal,
  });
  return data;
}

export async function downloadFile(docId, fileName, version) {
  const blob = await fetchBlob(docId, { version });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName || "document";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** axios with responseType "blob" returns error bodies as blobs too; read the JSON detail out. */
export async function blobErrorMessage(e, fallback = "Something went wrong") {
  const data = e?.response?.data;
  if (data instanceof Blob) {
    try {
      const body = JSON.parse(await data.text());
      if (typeof body?.detail === "string") return body.detail;
    } catch {
      /* not JSON */
    }
  }
  return e?.message || fallback;
}
