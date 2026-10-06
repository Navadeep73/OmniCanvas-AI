/* main.js: wires the whole app together. */

import { $, announce, bus, state, toast } from "./core.js";
import { api } from "./api.js";
import { ChatView } from "./chat.js";
import { composer } from "./composer.js";
import { lens } from "./lens.js";
import { Orb } from "./orb.js";
import { palette } from "./palette.js";
import { sessions } from "./sessions.js";

const app = $("#app");
const feed = $("#feed");
const topTitle = $("#topTitle");

let controller = null;
let messageCount = 0;
let orbHero = null;
let orbMini = null;
let ingestMode = "idle";

/* ------------------------------------------------------------------ theme */

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("oc.theme", theme);
  const button = $("#themeBtn");
  button.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
  button.innerHTML = `<svg class="icon" aria-hidden="true"><use href="#i-${theme === "dark" ? "sun" : "moon"}"/></svg>`;
  const sheet = document.querySelector('link[href*="highlight.js"]');
  if (sheet) {
    sheet.href = `https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/${theme === "dark" ? "github-dark" : "github"}.min.css`;
  }
  bus.emit("theme:changed", theme);
}
const savedTheme = localStorage.getItem("oc.theme") || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
applyTheme(savedTheme);
$("#themeBtn").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

/* -------------------------------------------------------------------- orbs */

function applyOrbMode() {
  const mode = state.streaming ? "thinking" : ingestMode;
  orbHero?.setMode(mode);
  orbMini?.setMode(mode);
}
bus.on("orb:mode", (mode) => { ingestMode = mode; applyOrbMode(); });

/* --------------------------------------------------------------- chat view */

const chat = new ChatView({
  onCite: (source, chip) => lens.showSource({ docId: source.doc_id, page: source.page, snippet: source.snippet, anchor: chip }),
  onPreview: ({ lang, code }) => {
    const normalized = { htm: "html", js: "javascript", react: "jsx" }[lang] || lang;
    lens.showArtifacts([{ id: "adhoc", lang: normalized, title: "Preview", code }]);
  },
  onArtifacts: (list, index) => lens.showArtifacts(list, index),
  onRegenerate: () => {
    chat.removeLastAssistant();
    send("", { regenerate: true });
  },
});

bus.on("doc:open", (doc) => lens.showSource({ docId: doc.id, page: 1 }));

/* ------------------------------------------------------------------ sending */

async function ensureSession() {
  if (state.sessionId) return state.sessionId;
  const session = await sessions.create();
  await selectSession(session.id, { force: true });
  return session.id;
}

async function send(text, { regenerate = false } = {}) {
  if (state.streaming) return;
  let sessionId;
  try {
    sessionId = await ensureSession();
  } catch (error) {
    return toast("Can't reach the server. Is it running?", { error: true });
  }

  state.streaming = true;
  composer.setStreaming();
  applyOrbMode();
  if (!regenerate) {
    chat.addUser(text);
    messageCount += 1;
  }
  const message = chat.beginAssistant();
  controller = new AbortController();

  let done = null;
  let failed = false;
  try {
    await api.stream(
      { session_id: sessionId, message: regenerate ? "" : text, provider: state.provider, temperature: 0.4, regenerate },
      (event) => {
        if (event.type === "meta") message.setMeta(event);
        else if (event.type === "token") message.push(event.text);
        else if (event.type === "done") done = event;
        else if (event.type === "error") { failed = true; message.fail(event.message); }
      },
      controller.signal
    );
  } catch (error) {
    if (error.name !== "AbortError") {
      failed = true;
      message.fail(error.message || "Something went wrong.");
    }
  } finally {
    state.streaming = false;
    controller = null;
    composer.setStreaming();
    applyOrbMode();
  }

  if (done) {
    message.finish(done);
    messageCount += 1;
    sessions.touch(sessionId, done.title);
    if (done.title) topTitle.textContent = done.title;
    if (done.artifacts?.length) lens.showArtifacts(done.artifacts, 0);
    announce("Answer ready");
  } else if (!failed) {
    // Stopped by the user: keep whatever streamed so far.
    if (message.isEmpty) message.root.remove();
    else message.finish({}, { allowRegenerate: true });
    messageCount += message.isEmpty ? 0 : 1;
  }
  composer.setConversationLength(messageCount);
  chat.stickToBottom(true);
}

/* ----------------------------------------------------------------- sessions */

async function selectSession(id, { force = false } = {}) {
  if (!force && id === state.sessionId) return;
  controller?.abort();
  state.sessionId = id;
  bus.emit("session:changed");

  const session = state.sessions.find((s) => s.id === id);
  topTitle.textContent = session?.title || "New chat";
  document.title = session && session.title !== "New chat" ? `${session.title} | OmniCanvas` : "OmniCanvas";
  app.classList.remove("rail-open");

  try {
    const [messages] = await Promise.all([api.messages(id), composer.loadDocs(id)]);
    messageCount = messages.length;
    chat.renderHistory(messages);
  } catch (error) {
    messageCount = 0;
    chat.showHero();
  }
  composer.setConversationLength(messageCount);
}

async function newChat() {
  if (!state.streaming && messageCount === 0 && state.docs.length === 0 && state.sessionId) {
    composer.focus();
    return;
  }
  try {
    const session = await sessions.create();
    await selectSession(session.id, { force: true });
    lens.close();
    composer.focus();
  } catch (error) {
    toast("Couldn't start a new chat.", { error: true });
  }
}

bus.on("session:select", (id) => selectSession(id));
bus.on("session:renamed", (session) => {
  if (session.id === state.sessionId) topTitle.textContent = session.title;
});
bus.on("session:deleted", async (id) => {
  if (id !== state.sessionId) return;
  const next = sessions.visible().find((s) => s.id !== id);
  state.sessionId = null;
  if (next) await selectSession(next.id, { force: true });
  else await newChat();
});

$("#newChat").addEventListener("click", newChat);
composer.init({ send, stop: () => controller?.abort(), ensureSession });

/* ---------------------------------------------------------------- providers */

const providerBtn = $("#providerBtn");
const providerMenu = $("#providerMenu");

function renderProvider() {
  const providers = state.health?.providers || {};
  const current = providers[state.provider];
  $("#providerLabel").textContent = current?.label || (state.provider === "groq" ? "GPT-OSS 120B on Groq" : "Gemini 2.5 Flash");
  const dot = $("#providerDot");
  const isConfigured = current ? Boolean(current.configured) : true;
  dot.className = `dot ${isConfigured ? "ok" : "off"}`;


  providerMenu.replaceChildren(
    ...Object.entries(providers).map(([key, info]) => {
      const item = document.createElement("button");
      item.className = "menu-item";
      item.setAttribute("role", "menuitemradio");
      item.setAttribute("aria-checked", String(key === state.provider));
      item.disabled = !info.configured;
      item.innerHTML = `<span class="dot ${info.configured ? "ok" : "off"}"></span>
        <span><strong></strong><small></small></span>
        <svg class="icon check" aria-hidden="true"><use href="#i-check"/></svg>`;
      item.querySelector("strong").textContent = info.label;
      item.querySelector("small").textContent = info.configured ? info.model : `Add ${key.toUpperCase()}_API_KEY to .env to enable`;
      item.addEventListener("click", () => {
        setProvider(key);
        closeProviderMenu();
      });
      return item;
    })
  );
}

function setProvider(key) {
  state.provider = key;
  localStorage.setItem("oc.provider", key);
  renderProvider();
}

function closeProviderMenu() {
  providerMenu.classList.remove("open");
  providerBtn.setAttribute("aria-expanded", "false");
}

providerBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  const open = providerMenu.classList.toggle("open");
  providerBtn.setAttribute("aria-expanded", String(open));
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".popover-anchor")) closeProviderMenu();
});

/* -------------------------------------------------------------- layout bits */

const collapseRail = (collapsed) => {
  app.classList.toggle("rail-collapsed", collapsed);
  $("#railExpand").hidden = !collapsed;
  localStorage.setItem("oc.railCollapsed", collapsed ? "1" : "0");
};
$("#railCollapse").addEventListener("click", () => collapseRail(true));
$("#railExpand").addEventListener("click", () => collapseRail(false));
if (localStorage.getItem("oc.railCollapsed") === "1") collapseRail(true);

$("#mobileMenu").addEventListener("click", () => app.classList.add("rail-open"));
$("#scrim").addEventListener("click", () => app.classList.remove("rail-open"));
$("#exportBtn").addEventListener("click", () => state.sessionId && window.open(api.exportUrl(state.sessionId), "_blank"));
$("#heroUpload").addEventListener("click", () => composer.openFilePicker());
$("#heroExamples").addEventListener("click", (event) => {
  const prompt = event.target.closest("button")?.dataset.prompt;
  if (prompt) send(prompt);
});
feed.addEventListener("scroll", () => $("#topbar").classList.toggle("scrolled", feed.scrollTop > 4), { passive: true });

/* ------------------------------------------------------------------ palette */

palette.register([
  { label: "New chat", hint: "Alt N", run: newChat },
  { label: "Attach a file", run: () => composer.openFilePicker() },
  { label: "Toggle source and canvas panel", hint: "Alt L", run: () => lens.toggle() },
  { label: "Switch theme", run: () => $("#themeBtn").click() },
  { label: "Export this chat as Markdown", run: () => $("#exportBtn").click() },
  { label: "Use Gemini", run: () => state.health?.providers.gemini.configured ? setProvider("gemini") : toast("Gemini isn't configured.", { error: true }) },
  { label: "Use Groq", run: () => state.health?.providers.groq.configured ? setProvider("groq") : toast("Groq isn't configured.", { error: true }) },
  { label: "Hide or show chat list", run: () => collapseRail(!app.classList.contains("rail-collapsed")) },
  { label: "Search chats", run: () => { collapseRail(false); $("#sessionSearch").focus(); } },
]);
$("#paletteBtn").addEventListener("click", () => palette.open());

document.addEventListener("keydown", (event) => {
  const mod = event.metaKey || event.ctrlKey;
  if (mod && event.key.toLowerCase() === "k") { event.preventDefault(); palette.isOpen() ? palette.close() : palette.open(); }
  else if (event.altKey && event.key.toLowerCase() === "n") { event.preventDefault(); newChat(); }
  else if (event.altKey && event.key.toLowerCase() === "l") { event.preventDefault(); lens.toggle(); }
  else if (event.key === "Escape") { closeProviderMenu(); app.classList.remove("rail-open"); }
});

/* --------------------------------------------------------------------- boot */

async function boot() {
  orbHero = new Orb($("#orbStage"), { points: 2400, threads: true });
  orbMini = new Orb($("#miniOrb"), { points: 420, threads: false, mini: true });

  try {
    const [health] = await Promise.all([api.health(), sessions.load()]);
    state.health = health;

    // If the saved provider has no key but the other does, switch quietly.
    const providers = health.providers;
    if (!providers[state.provider]?.configured) {
      const usable = Object.keys(providers).find((key) => providers[key].configured);
      if (usable) state.provider = usable;
    }
    renderProvider();

    if (!health.providers.gemini.configured && !health.providers.groq.configured) {
      toast("No API key found. Add GEMINI_API_KEY to your .env file to start chatting.", { error: true, duration: 9000 });
    } else if (!health.embeddings.semantic && !sessionStorage.getItem("oc.hashNote")) {
      sessionStorage.setItem("oc.hashNote", "1");
      toast("Using offline keyword search. Add a Gemini key for semantic matching.", { duration: 7000 });
    }

    const urlParams = new URLSearchParams(window.location.search);
    const urlSession = urlParams.get("session");
    if (urlSession && state.sessions.some((s) => s.id === urlSession)) {
      await selectSession(urlSession, { force: true });
    } else if (state.sessions.length) {
      await selectSession(state.sessions[0].id, { force: true });
    } else {
      chat.showHero();
    }

  } catch (error) {
    chat.showHero();
    toast("Can't reach the OmniCanvas server. Start it with: uvicorn main:app", { error: true, duration: 9000 });
  }
}

boot();
