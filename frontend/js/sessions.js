/* sessions.js: the left rail. Grouped by day, searchable, inline rename, delete with undo. */

import { $, bus, dayGroup, el, icon, state, toast } from "./core.js";
import { api } from "./api.js";

const listEl = $("#sessionList");
const searchEl = $("#sessionSearch");
const hidden = new Set(); // soft-deleted ids waiting out the undo window

function visibleSessions() {
  const query = searchEl.value.trim().toLowerCase();
  return state.sessions.filter((s) => !hidden.has(s.id) && (!query || s.title.toLowerCase().includes(query)));
}

function startRename(item, session) {
  const title = item.querySelector(".session-title");
  title.contentEditable = "true";
  title.focus();
  document.getSelection().selectAllChildren(title);

  const finish = async (commit) => {
    title.contentEditable = "false";
    title.removeEventListener("blur", onBlur);
    title.removeEventListener("keydown", onKey);
    const next = title.textContent.trim().slice(0, 120);
    if (commit && next && next !== session.title) {
      session.title = next;
      try { await api.renameSession(session.id, next); } catch (e) { toast(e.message, { error: true }); }
      bus.emit("session:renamed", session);
    }
    render();
  };
  const onBlur = () => finish(true);
  const onKey = (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    if (e.key === "Escape") { e.preventDefault(); finish(false); }
  };
  title.addEventListener("blur", onBlur);
  title.addEventListener("keydown", onKey);
}

function remove(session) {
  hidden.add(session.id);
  const wasActive = state.sessionId === session.id;
  render();
  if (wasActive) bus.emit("session:deleted", session.id);

  let undone = false;
  toast("Chat deleted", {
    action: "Undo",
    duration: 5200,
    onAction: () => {
      undone = true;
      hidden.delete(session.id);
      render();
      if (wasActive) bus.emit("session:select", session.id);
    },
  });
  setTimeout(async () => {
    if (undone) return;
    try { await api.deleteSession(session.id); } catch { /* already gone */ }
    state.sessions = state.sessions.filter((s) => s.id !== session.id);
    hidden.delete(session.id);
  }, 5300);
}

export function render() {
  const sessions = visibleSessions();
  listEl.replaceChildren();

  if (!sessions.length) {
    listEl.append(el("div", { class: "empty-note", text: searchEl.value ? "No chats match that search." : "Your chats will appear here." }));
    return;
  }

  let lastGroup = "";
  for (const session of sessions) {
    const group = dayGroup(session.updated_at);
    if (group !== lastGroup) {
      listEl.append(el("div", { class: "group-label", text: group }));
      lastGroup = group;
    }
    const item = el(
      "div",
      { class: `session${session.id === state.sessionId ? " active" : ""}`, role: "button", tabindex: "0", "data-id": session.id },
      el("span", { class: "session-title", text: session.title }),
      el("button", { class: "icon-btn", "aria-label": "Rename chat", title: "Rename", html: icon("edit"), "data-act": "rename" }),
      el("button", { class: "icon-btn", "aria-label": "Delete chat", title: "Delete", html: icon("trash"), "data-act": "delete" })
    );
    item.addEventListener("click", (event) => {
      const act = event.target.closest("[data-act]")?.dataset.act;
      if (act === "rename") return startRename(item, session);
      if (act === "delete") return remove(session);
      if (item.querySelector('[contenteditable="true"]')) return;
      bus.emit("session:select", session.id);
    });
    item.addEventListener("dblclick", () => startRename(item, session));
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target === item) bus.emit("session:select", session.id);
      if (event.key === "F2") startRename(item, session);
    });
    listEl.append(item);
  }
}

export const sessions = {
  async load() {
    state.sessions = await api.sessions();
    render();
    return state.sessions;
  },
  async create() {
    const session = await api.createSession(state.provider);
    state.sessions.unshift(session);
    render();
    return session;
  },
  /** Update a title/time locally after a reply, and float the chat to the top. */
  touch(id, title) {
    const session = state.sessions.find((s) => s.id === id);
    if (!session) return;
    if (title) session.title = title;
    session.updated_at = new Date().toISOString();
    state.sessions = [session, ...state.sessions.filter((s) => s.id !== id)];
    render();
  },
  visible: visibleSessions,
  render,
};

searchEl.addEventListener("input", render);
bus.on("session:changed", render);
