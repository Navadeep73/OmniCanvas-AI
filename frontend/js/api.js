/* api.js: REST client plus the Server-Sent-Events chat stream. */

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* not json */ }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request("/api/health"),
  sessions: () => request("/api/sessions"),
  createSession: (provider) => request("/api/sessions", json("POST", { title: "New chat", model_provider: provider })),
  renameSession: (id, title) => request(`/api/sessions/${id}`, json("PATCH", { title })),
  deleteSession: (id) => request(`/api/sessions/${id}`, { method: "DELETE" }),
  messages: (id) => request(`/api/sessions/${id}/messages`),
  documents: (id) => request(`/api/sessions/${id}/documents`),
  document: (id) => request(`/api/documents/${id}`),
  deleteDocument: (id) => request(`/api/documents/${id}`, { method: "DELETE" }),
  textPages: (id) => request(`/api/documents/${id}/text`),
  fileUrl: (id) => `/api/documents/${id}/file`,
  exportUrl: (id) => `/api/export/${id}/markdown`,

  /** Upload with progress. Resolves to the new document row. */
  upload(file, sessionId, onProgress) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      form.append("session_id", sessionId);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      xhr.upload.onprogress = (event) => event.lengthComputable && onProgress?.(event.loaded / event.total);
      xhr.onload = () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch { /* ignore */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new Error(body.detail || `Upload failed (${xhr.status})`));
      };
      xhr.onerror = () => reject(new Error("Could not reach the server."));
      xhr.send(form);
    });
  },

  /**
   * Stream a chat reply. Calls onEvent for each {type: meta|token|done|error}.
   * Abort with the AbortController signal to stop generation.
   */
  async stream(payload, onEvent, signal) {
    const response = await fetch("/api/chat/stream", { ...json("POST", payload), signal });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try { detail = (await response.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (line) {
          try { onEvent(JSON.parse(line.slice(6))); } catch { /* skip malformed frame */ }
        }
      }
    }
  },
};
