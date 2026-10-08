import { API_BASE, api, tokens } from "@/lib/api";

/** POST that expects a text/event-stream reply. The bearer token goes in a header, never the URL. */
function postStream(path, body, signal) {
  const headers = { "Content-Type": "application/json", Accept: "text/event-stream" };
  const access = tokens.access;
  if (access) headers.Authorization = `Bearer ${access}`;
  return fetch(`${API_BASE}${path}`, { method: "POST", headers, body: JSON.stringify(body), signal });
}

function parseEvent(raw) {
  let event = "message";
  const data = [];
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

/**
 * Sends a chat message and feeds each server-sent event to onEvent(event, data).
 * Rejects with an Error carrying `.status` when the server refuses the request (429, 503, …);
 * rejects with an AbortError when `signal` is aborted (the Stop button).
 */
export async function streamMessage(conversationId, body, { signal, onEvent }) {
  const path = `/ai/conversations/${conversationId}/messages`;
  let res = await postStream(path, body, signal);
  if (res.status === 401 && tokens.refresh) {
    // Let the axios interceptor rotate the access token, then retry once.
    try { await api.get("/auth/me"); } catch { /* interceptor handles sign-out */ }
    res = await postStream(path, body, signal);
  }
  if (!res.ok || !res.body) {
    let detail = null;
    try { detail = (await res.json())?.detail; } catch { /* not JSON */ }
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => d?.msg).filter(Boolean).join(" ")
      : `Request failed (${res.status})`;
    const err = new Error(message || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.search(/\r?\n\r?\n/)) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx).replace(/^\r?\n\r?\n/, "");
      const parsed = parseEvent(raw);
      if (parsed) onEvent(parsed.event, parsed.data);
    }
  }
  const tail = parseEvent(buffer);
  if (tail) onEvent(tail.event, tail.data);
}
