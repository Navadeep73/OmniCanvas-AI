/* core.js: tiny helpers, event bus, shared state, toasts. No dependencies. */

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(child));
  }
  return node;
}

export const icon = (name, extra = "") => `<svg class="icon ${extra}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

export const escapeHtml = (text) =>
  String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function debounce(fn, wait = 150) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---- event bus ---- */
const listeners = new Map();
export const bus = {
  on(event, fn) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(fn);
    return () => listeners.get(event).delete(fn);
  },
  emit(event, payload) {
    listeners.get(event)?.forEach((fn) => fn(payload));
  },
};

/* ---- shared state ---- */
export const state = {
  sessionId: null,
  sessions: [],
  docs: [],
  provider: localStorage.getItem("oc.provider") || "gemini",
  health: null,
  streaming: false,
};

/* ---- accessibility announcer ---- */
export function announce(text) {
  const region = $("#announcer");
  if (!region) return;
  region.textContent = "";
  setTimeout(() => (region.textContent = text), 40);
}

/* ---- toasts ---- */
export function toast(message, { action, onAction, error = false, duration = 4500 } = {}) {
  const host = $("#toasts");
  const node = el("div", { class: `toast${error ? " error" : ""}` }, el("span", { text: message }));
  let timer;
  const close = () => {
    clearTimeout(timer);
    node.remove();
  };
  if (action) {
    node.append(
      el("button", {
        text: action,
        onClick: () => {
          onAction?.();
          close();
        },
      })
    );
  }
  host.append(node);
  timer = setTimeout(close, duration);
  return close;
}

/* ---- formatting ---- */
export function dayGroup(isoDate) {
  const date = new Date(isoDate);
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const days = Math.floor((startOfToday - date) / 86400000);
  if (date >= startOfToday) return "Today";
  if (days < 1) return "Yesterday";
  if (days < 7) return "Previous 7 days";
  return "Earlier";
}

export const kindIcon = (kind) => (kind === "image" ? "image" : "file");

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
