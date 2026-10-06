/* composer.js: the message box, attachments, drag-and-drop, dictation and suggestions. */

import { $, bus, el, formatBytes, icon, kindIcon, state, toast } from "./core.js";
import { api } from "./api.js";
import { webfx } from "./webfx.js";

const ui = {
  input: $("#input"), send: $("#sendBtn"), attach: $("#attachBtn"), file: $("#fileInput"), mic: $("#micBtn"),
  chips: $("#chips"), suggest: $("#suggest"), veil: $("#dropveil"), composer: $("#composer"),
};

const MAX_BYTES = 25 * 1024 * 1024;
let handlers = { send: () => {}, stop: () => {}, ensureSession: async () => state.sessionId };
let uploads = []; // in-flight uploads not yet known to the server
let conversationLength = 0;
const pollers = new Map();

/* ----------------------------------------------------------------- input */

function autosize() {
  ui.input.style.height = "auto";
  ui.input.style.height = `${Math.min(ui.input.scrollHeight, 200)}px`;
}

function syncSend() {
  const hasText = ui.input.value.trim().length > 0;
  ui.send.disabled = !state.streaming && !hasText;
  ui.send.classList.toggle("stop", state.streaming);
  ui.send.setAttribute("aria-label", state.streaming ? "Stop generating" : "Send message");
  ui.send.innerHTML = icon(state.streaming ? "stop" : "up");
  renderSuggestions();
}

function submit() {
  if (state.streaming) return handlers.stop();
  const text = ui.input.value.trim();
  if (!text) return;
  ui.input.value = "";
  autosize();
  syncSend();
  handlers.send(text);
}

ui.input.addEventListener("input", () => { autosize(); syncSend(); });
ui.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
});
ui.send.addEventListener("click", submit);
ui.input.addEventListener("paste", (event) => {
  const files = [...(event.clipboardData?.files || [])];
  if (files.length) {
    event.preventDefault();
    addFiles(files);
  }
});

/* ----------------------------------------------------------- suggestions */

function renderSuggestions() {
  const ready = state.docs.some((d) => d.status === "ready");
  const show = ready && conversationLength < 2 && !state.streaming && !ui.input.value.trim();
  ui.suggest.hidden = !show;
  if (!show) return;
  const prompts = [
    "Summarize this in five points",
    "What are the key terms I should know?",
    "Explain the main idea visually",
  ];
  ui.suggest.replaceChildren(...prompts.map((text) => el("button", { type: "button", text, onClick: () => handlers.send(text) })));
}

/* ------------------------------------------------------------------ chips */

function statusText(doc) {
  switch (doc.status) {
    case "uploading": return `Uploading ${Math.round((doc.progress || 0))}%`;
    case "queued":
    case "reading": return "Reading";
    case "indexing": return `Indexing ${doc.progress}%`;
    case "ready": return doc.pages > 1 ? `${doc.pages} ${doc.kind === "text" ? "sections" : "pages"}` : "Ready";
    case "failed": return "Failed";
    default: return "";
  }
}

export function renderChips() {
  const items = [...state.docs, ...uploads];
  ui.chips.hidden = items.length === 0;
  ui.chips.replaceChildren(
    ...items.map((doc) => {
      const percent = doc.status === "ready" ? 0 : doc.status === "uploading" ? doc.progress : doc.progress;
      const chip = el(
        "div",
        { class: `chip ${doc.status}`, title: doc.error || `${doc.filename} (${formatBytes(doc.size || 0)})`, "data-id": doc.id },
        el("span", { html: icon(kindIcon(doc.kind)) }),
        el("span", { class: "name", text: doc.filename }),
        el("span", { class: "state", text: statusText(doc) }),
        doc.local ? null : el("button", { class: "x", type: "button", "aria-label": `Remove ${doc.filename}`, html: icon("x", ""), "data-act": "remove" }),
        percent ? el("span", { class: "bar", style: `width:${percent}%` }) : null
      );
      return chip;
    })
  );
  renderSuggestions();
}

ui.chips.addEventListener("click", async (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  const doc = state.docs.find((d) => d.id === chip.dataset.id);
  if (!doc) return;
  if (event.target.closest('[data-act="remove"]')) {
    try {
      await api.deleteDocument(doc.id);
      state.docs = state.docs.filter((d) => d.id !== doc.id);
      stopPolling(doc.id);
      renderChips();
      bus.emit("docs:changed");
    } catch (e) { toast(e.message, { error: true }); }
  } else if (doc.status === "ready") {
    bus.emit("doc:open", doc);
  }
});

/* ---------------------------------------------------------------- uploads */

function stopPolling(id) {
  clearInterval(pollers.get(id));
  pollers.delete(id);
}

function updateIngestMode() {
  const busy = state.docs.some((d) => !["ready", "failed"].includes(d.status)) || uploads.length > 0;
  bus.emit("orb:mode", busy ? "ingesting" : "idle");
}

function watch(doc, web) {
  pollers.set(
    doc.id,
    setInterval(async () => {
      try {
        const next = await api.document(doc.id);
        const index = state.docs.findIndex((d) => d.id === doc.id);
        if (index === -1) return stopPolling(doc.id);
        state.docs[index] = next;
        webfx.progress(web, next.progress / 100);
        renderChips();
        if (next.status === "ready" || next.status === "failed") {
          stopPolling(doc.id);
          webfx.finish(web, next.status === "ready");
          updateIngestMode();
          bus.emit("docs:changed");
          if (next.status === "failed") toast(next.error || "That file couldn't be indexed.", { error: true, duration: 7000 });
          else toast(`${next.filename} is ready. Ask away.`);
        }
      } catch { /* transient: keep polling */ }
    }, 700)
  );
}

export async function addFiles(fileList) {
  const files = [...fileList];
  for (const file of files) {
    if (file.size > MAX_BYTES) {
      toast(`${file.name} is larger than 25 MB.`, { error: true });
      continue;
    }
    const sessionId = await handlers.ensureSession();
    const local = { id: `local-${crypto.randomUUID()}`, filename: file.name, kind: file.type.startsWith("image/") ? "image" : "pdf", size: file.size, status: "uploading", progress: 0, local: true };
    uploads.push(local);
    renderChips();
    updateIngestMode();
    const web = webfx.start(ui.attach);

    try {
      const doc = await api.upload(file, sessionId, (fraction) => {
        local.progress = Math.round(fraction * 100);
        webfx.progress(web, fraction * 0.25);
        renderChips();
      });
      uploads = uploads.filter((u) => u !== local);
      state.docs.push(doc);
      renderChips();
      bus.emit("docs:changed");
      watch(doc, web);
    } catch (error) {
      uploads = uploads.filter((u) => u !== local);
      webfx.finish(web, false);
      renderChips();
      updateIngestMode();
      toast(error.message, { error: true, duration: 7000 });
    }
  }
}

ui.attach.addEventListener("click", () => ui.file.click());
ui.file.addEventListener("change", () => {
  if (ui.file.files.length) addFiles(ui.file.files);
  ui.file.value = "";
});

// Drag and drop anywhere on the page.
let dragDepth = 0;
const hasFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (event) => {
  if (!hasFiles(event)) return;
  dragDepth++;
  ui.veil.classList.add("show");
});
window.addEventListener("dragover", (event) => hasFiles(event) && event.preventDefault());
window.addEventListener("dragleave", (event) => {
  if (!hasFiles(event)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) ui.veil.classList.remove("show");
});
window.addEventListener("drop", (event) => {
  if (!hasFiles(event)) return;
  event.preventDefault();
  dragDepth = 0;
  ui.veil.classList.remove("show");
  addFiles(event.dataTransfer.files);
});

/* ----------------------------------------------------------------- voice */

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;

ui.mic.addEventListener("click", () => {
  if (!Recognition) return toast("Dictation isn't supported in this browser. Try Chrome or Edge.", { error: true });
  if (recognizer) { recognizer.stop(); return; }

  const base = ui.input.value ? `${ui.input.value.trimEnd()} ` : "";
  recognizer = new Recognition();
  recognizer.interimResults = true;
  recognizer.lang = navigator.language || "en-US";
  recognizer.onresult = (event) => {
    let transcript = "";
    for (let i = 0; i < event.results.length; i++) transcript += event.results[i][0].transcript;
    ui.input.value = base + transcript;
    autosize();
    syncSend();
  };
  const end = () => {
    recognizer = null;
    ui.mic.classList.remove("recording");
    ui.mic.setAttribute("aria-label", "Dictate a message");
  };
  recognizer.onend = end;
  recognizer.onerror = (event) => {
    if (event.error === "not-allowed") toast("Microphone access was blocked.", { error: true });
    end();
  };
  recognizer.start();
  ui.mic.classList.add("recording");
  ui.mic.setAttribute("aria-label", "Stop dictation");
});

/* ---------------------------------------------------------------- public */

export const composer = {
  init(next) { handlers = { ...handlers, ...next }; syncSend(); autosize(); },
  focus: () => ui.input.focus(),
  setText(text) { ui.input.value = text; autosize(); syncSend(); },
  setStreaming() { syncSend(); },
  setConversationLength(n) { conversationLength = n; renderSuggestions(); },
  openFilePicker: () => ui.file.click(),
  async loadDocs(sessionId) {
    [...pollers.keys()].forEach(stopPolling);
    uploads = [];
    try {
      state.docs = await api.documents(sessionId);
    } catch { state.docs = []; }
    renderChips();
    bus.emit("docs:changed");
    // Resume progress for anything still indexing (e.g. after a page reload).
    state.docs.filter((d) => !["ready", "failed"].includes(d.status)).forEach((d) => watch(d, null));
    updateIngestMode();
  },
};
