/* lens.js: the right-hand panel.
   Source tab  - PDF.js viewer that jumps to a cited page and highlights the passage.
   Canvas tab  - runs model-written HTML/SVG/JSX/Mermaid in a sandboxed iframe. */

import { $, $$, bus, debounce, el, state, toast } from "./core.js";
import { api } from "./api.js";
import { webfx } from "./webfx.js";

const app = $("#app");
const PDF_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

/* ------------------------------------------------------------------ shell */

const ui = {
  tabSource: $("#tabSource"), tabCanvas: $("#tabCanvas"),
  sourcePanel: $("#sourcePanel"), canvasPanel: $("#canvasPanel"),
  toggle: $("#lensToggle"),
};

let tab = "source";

function setTab(next) {
  tab = next;
  ui.tabSource.setAttribute("aria-selected", String(next === "source"));
  ui.tabCanvas.setAttribute("aria-selected", String(next === "canvas"));
  ui.sourcePanel.hidden = next !== "source";
  ui.canvasPanel.hidden = next !== "canvas";
  if (next === "source") refreshSourceChrome();
}

function open(nextTab) {
  if (nextTab) setTab(nextTab);
  app.classList.add("lens-open");
  ui.toggle.setAttribute("aria-pressed", "true");
  bus.emit("lens:changed", true);
}

function close() {
  app.classList.remove("lens-open");
  ui.toggle.setAttribute("aria-pressed", "false");
  bus.emit("lens:changed", false);
}

const isOpen = () => app.classList.contains("lens-open");

ui.tabSource.addEventListener("click", () => setTab("source"));
ui.tabCanvas.addEventListener("click", () => setTab("canvas"));
ui.toggle.addEventListener("click", () => (isOpen() ? close() : open()));
$("#lensClose").addEventListener("click", close);

// Drag (or arrow-key) resizing.
const resizer = $("#resizer");
const setWidth = (px) => {
  const clamped = Math.max(360, Math.min(px, window.innerWidth * 0.7));
  document.documentElement.style.setProperty("--lens-w", `${clamped}px`);
  localStorage.setItem("oc.lensWidth", String(Math.round(clamped)));
  rerenderPdfSoon();
};
const saved = Number(localStorage.getItem("oc.lensWidth"));
if (saved) document.documentElement.style.setProperty("--lens-w", `${saved}px`);

resizer.addEventListener("pointerdown", (event) => {
  resizer.setPointerCapture(event.pointerId);
  app.classList.add("resizing");
  const move = (e) => setWidth(window.innerWidth - e.clientX);
  const up = () => {
    app.classList.remove("resizing");
    resizer.removeEventListener("pointermove", move);
    resizer.removeEventListener("pointerup", up);
  };
  resizer.addEventListener("pointermove", move);
  resizer.addEventListener("pointerup", up);
});
resizer.addEventListener("keydown", (event) => {
  const current = $("#lens").getBoundingClientRect().width;
  if (event.key === "ArrowLeft") setWidth(current + 32);
  if (event.key === "ArrowRight") setWidth(current - 32);
});

/* ------------------------------------------------------------ source viewer */

const src = {
  bar: $("#sourceBar"), select: $("#docSelect"), scroll: $("#sourceScroll"), empty: $("#sourceEmpty"),
  prev: $("#prevPage"), next: $("#nextPage"), label: $("#pageLabel"),
};

const pdfCache = new Map();
const textCache = new Map();
let view = { docId: null, page: 1, pages: 1, snippet: "" };
let renderToken = 0;

const readyDocs = () => state.docs.filter((d) => d.status === "ready");

function refreshSourceChrome() {
  const docs = readyDocs();
  const hasDocs = docs.length > 0;
  src.bar.hidden = !hasDocs;
  src.scroll.hidden = !hasDocs || !view.docId;
  src.empty.hidden = hasDocs && !!view.docId;

  src.select.replaceChildren(...docs.map((d) => el("option", { value: d.id, text: d.filename })));
  src.select.hidden = docs.length < 2;
  if (view.docId) src.select.value = view.docId;
}

function normalise(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function highlightSpans(spans, snippet) {
  if (!snippet) return null;
  const snippetNorm = ` ${normalise(snippet)} `;
  const snippetWords = new Set(snippetNorm.split(" ").filter((w) => w.length > 2));
  let first = null;
  for (const span of spans) {
    const text = normalise(span.textContent || "");
    if (text.length < 3) continue;
    const words = text.split(" ").filter((w) => w.length > 2);
    if (words.length < 2 && text.length < 10) continue; // skip lone common words
    const contained = snippetNorm.includes(` ${text} `) || (text.length >= 10 && snippetNorm.includes(text));
    const overlap = words.length >= 2 && words.filter((w) => snippetWords.has(w)).length / words.length >= 0.75;
    if (contained || overlap) {
      span.classList.add("hl");
      first ||= span;
    }
  }
  return first;
}

async function loadPdf(doc) {
  if (!window.pdfjsLib) throw new Error("The PDF viewer library could not load. Check your connection.");
  window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDF_WORKER;
  if (!pdfCache.has(doc.id)) pdfCache.set(doc.id, window.pdfjsLib.getDocument({ url: api.fileUrl(doc.id) }).promise);
  return pdfCache.get(doc.id);
}

async function renderPdfPage(doc, pageNumber, snippet, token) {
  const pdf = await loadPdf(doc);
  if (token !== renderToken) return;
  view.pages = pdf.numPages;
  view.page = Math.min(Math.max(1, pageNumber), pdf.numPages);

  const page = await pdf.getPage(view.page);
  if (token !== renderToken) return;

  const base = page.getViewport({ scale: 1 });
  const available = Math.max(280, src.scroll.clientWidth - 36);
  const scale = Math.min(available / base.width, 2.2);
  const viewport = page.getViewport({ scale });
  const ratio = Math.min(window.devicePixelRatio || 1, 2);

  const canvas = el("canvas");
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;

  const textLayer = el("div", { class: "textLayer" });
  textLayer.style.setProperty("--scale-factor", String(scale));
  const holder = el("div", { class: "pdf-page" }, canvas, textLayer);
  holder.style.width = canvas.style.width;
  holder.style.height = canvas.style.height;

  await page.render({ canvasContext: canvas.getContext("2d"), viewport, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null }).promise;
  if (token !== renderToken) return;

  const spans = [];
  try {
    const content = await page.getTextContent();
    await window.pdfjsLib.renderTextLayer({ textContentSource: content, container: textLayer, viewport, textDivs: spans }).promise;
  } catch { /* highlighting is a bonus; the page itself is already visible */ }
  if (token !== renderToken) return;

  src.scroll.replaceChildren(holder);
  const first = highlightSpans(spans, snippet);
  if (first) first.scrollIntoView({ block: "center", behavior: "smooth" });
  else src.scroll.scrollTop = 0;
}

async function renderTextPage(doc, pageNumber, snippet, token) {
  if (!textCache.has(doc.id)) textCache.set(doc.id, api.textPages(doc.id).then((r) => r.pages));
  const pages = await textCache.get(doc.id);
  if (token !== renderToken) return;
  view.pages = pages.length;
  view.page = Math.min(Math.max(1, pageNumber), pages.length);
  const text = pages[view.page - 1] || "";

  const box = el("div", { class: "text-doc" });
  const words = snippet.split(/\s+/).filter(Boolean).slice(0, 7).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const match = words.length >= 3 ? new RegExp(words.join("\\s+"), "i").exec(text) : null;
  if (match) {
    const end = Math.min(text.length, match.index + Math.max(snippet.length, match[0].length));
    const mark = el("mark", { text: text.slice(match.index, end) });
    box.append(text.slice(0, match.index), mark, text.slice(end));
    src.scroll.replaceChildren(box);
    mark.scrollIntoView({ block: "center", behavior: "smooth" });
  } else {
    box.textContent = text;
    src.scroll.replaceChildren(box);
    src.scroll.scrollTop = 0;
  }
}

function renderImage(doc) {
  view.pages = 1;
  view.page = 1;
  src.scroll.replaceChildren(el("img", { class: "image-doc", src: api.fileUrl(doc.id), alt: doc.filename }));
}

function updateNav(doc) {
  const paged = doc.kind !== "image";
  src.prev.hidden = src.next.hidden = src.label.hidden = !paged;
  src.label.textContent = paged ? `${doc.kind === "text" ? "Section" : "Page"} ${view.page} of ${view.pages}` : "";
  src.prev.disabled = view.page <= 1;
  src.next.disabled = view.page >= view.pages;
}

async function renderSource() {
  const doc = state.docs.find((d) => d.id === view.docId);
  if (!doc) return refreshSourceChrome();
  refreshSourceChrome();
  const token = ++renderToken;
  try {
    if (doc.kind === "pdf") await renderPdfPage(doc, view.page, view.snippet, token);
    else if (doc.kind === "text") await renderTextPage(doc, view.page, view.snippet, token);
    else renderImage(doc);
    if (token === renderToken) updateNav(doc);
  } catch (error) {
    if (token !== renderToken) return;
    src.prev.hidden = src.next.hidden = src.label.hidden = true;
    src.scroll.replaceChildren(
      el("div", { class: "lens-empty" }, el("div", {},
        el("strong", { text: "Couldn't show this file here" }), error.message, el("br"), el("br"),
        el("a", { href: api.fileUrl(doc.id), target: "_blank", rel: "noopener", text: "Open the file in a new tab" })))
    );
  }
}

const rerenderPdfSoon = debounce(() => {
  if (isOpen() && tab === "source" && view.docId) renderSource();
}, 160);

function showSource({ docId, page = 1, snippet = "", anchor = null }) {
  const doc = state.docs.find((d) => d.id === docId) || readyDocs()[0];
  if (!doc) {
    toast("That document isn't available any more.", { error: true });
    return;
  }
  view = { docId: doc.id, page, pages: view.pages, snippet };
  open("source");
  renderSource();
  if (anchor) setTimeout(() => webfx.thread(anchor, $("#lensHead")), 340);
}

const go = (delta) => {
  view.page += delta;
  view.snippet = "";
  renderSource();
};
src.prev.addEventListener("click", () => go(-1));
src.next.addEventListener("click", () => go(1));
src.select.addEventListener("change", () => showSource({ docId: src.select.value, page: 1 }));

bus.on("docs:changed", () => {
  if (view.docId && !state.docs.some((d) => d.id === view.docId)) view = { docId: null, page: 1, pages: 1, snippet: "" };
  refreshSourceChrome();
});

/* ------------------------------------------------------------------- canvas */

const cv = {
  bar: $("#canvasBar"), select: $("#artifactSelect"), stage: $("#canvasStage"), code: $("#codeView"), empty: $("#canvasEmpty"),
  preview: $("#viewPreview"), codeBtn: $("#viewCode"),
};

let artifacts = [];
let current = 0;
let mode = "preview";
let device = "desktop";

const CDN = "https://cdnjs.cloudflare.com/ajax/libs";
const escapeForScript = (code) => code.replace(/<\/script/gi, "<\\/script");
const escapeHtml = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function buildSrcDoc(lang, code) {
  const meta = '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">';

  if (lang === "html") {
    return /<html[\s>]|<!doctype/i.test(code) ? code : `<!doctype html><html><head>${meta}</head><body>${code}</body></html>`;
  }
  if (lang === "svg") {
    return `<!doctype html><html><head>${meta}<style>html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#fff}svg{max-width:100%;max-height:100vh}</style></head><body>${code}</body></html>`;
  }
  if (lang === "css") {
    return `<!doctype html><html><head>${meta}<style>${code}</style></head><body><main style="max-width:640px;margin:40px auto;padding:0 20px"><h1>Heading one</h1><h2>Heading two</h2><p>Body text with a <a href="#">link</a> and <strong>strong</strong> words, so you can judge the typography.</p><button>Button</button> <input placeholder="Input"> <select><option>Select</option></select><ul><li>List item</li><li>Another item</li></ul></main></body></html>`;
  }
  if (lang === "javascript") {
    return `<!doctype html><html><head>${meta}<style>body{margin:0;background:#0f0d22;color:#e8e4ff;font:13px/1.6 ui-monospace,Menlo,monospace}#log{padding:14px;white-space:pre-wrap}.err{color:#ff8ca1}</style></head><body><div id="log"></div><script>
const log=document.getElementById('log');
const fmt=a=>typeof a==='string'?a:(()=>{try{return JSON.stringify(a,null,2)}catch(e){return String(a)}})();
['log','info','warn','error'].forEach(k=>{const o=console[k];console[k]=(...a)=>{const d=document.createElement('div');if(k==='error')d.className='err';d.textContent=a.map(fmt).join(' ');log.append(d);o.apply(console,a)}});
addEventListener('error',e=>console.error(e.message));
<\/script><script>${escapeForScript(code)}<\/script></body></html>`;
  }
  if (lang === "jsx") {
    let body = code
      .replace(/^\s*import\s+[^;]*?from\s+['"][^'"]+['"];?\s*$/gm, "")
      .replace(/^\s*export\s+default\s+function\s+/m, "function ")
      .replace(/^\s*export\s+default\s+class\s+/m, "class ")
      .replace(/^\s*export\s+default\s+\w+;?\s*$/m, "");
    const declaresHooks = /=\s*React\s*;/.test(body);
    const prelude = declaresHooks ? "" : "const { useState, useEffect, useRef, useMemo, useCallback, useReducer, useContext, createContext, Fragment } = React;\n";
    return `<!doctype html><html><head>${meta}<style>body{margin:0;font-family:system-ui,sans-serif}</style></head><body><div id="root"></div>
<script crossorigin src="${CDN}/react/18.2.0/umd/react.production.min.js"><\/script>
<script crossorigin src="${CDN}/react-dom/18.2.0/umd/react-dom.production.min.js"><\/script>
<script src="${CDN}/babel-standalone/7.24.7/babel.min.js"><\/script>
<script type="text/babel" data-presets="react">
${prelude}${escapeForScript(body)}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
<\/script></body></html>`;
  }
  if (lang === "mermaid") {
    return `<!doctype html><html><head>${meta}<style>body{margin:0;padding:24px;background:#fff;display:grid;place-items:center;min-height:100vh}</style></head><body><pre class="mermaid">${escapeHtml(code)}</pre>
<script src="${CDN}/mermaid/10.9.1/mermaid.min.js"><\/script><script>mermaid.initialize({startOnLoad:true,theme:'default'})<\/script></body></html>`;
  }
  return `<pre>${escapeHtml(code)}</pre>`;
}

const EXTENSIONS = { html: "html", svg: "svg", css: "css", javascript: "js", jsx: "jsx", mermaid: "mmd" };

function renderArtifact() {
  const item = artifacts[current];
  const has = Boolean(item);
  cv.bar.hidden = !has;
  cv.empty.hidden = has;
  cv.stage.hidden = !has || mode !== "preview";
  cv.code.hidden = !has || mode !== "code";
  if (!has) return;

  cv.select.hidden = artifacts.length < 2;
  cv.select.replaceChildren(...artifacts.map((a, i) => el("option", { value: i, text: a.title, selected: i === current })));
  cv.preview.setAttribute("aria-pressed", String(mode === "preview"));
  cv.codeBtn.setAttribute("aria-pressed", String(mode === "code"));
  $$("#devDesktop, #devTablet, #devPhone").forEach((b) => b.setAttribute("aria-pressed", String(b.id === `dev${device[0].toUpperCase()}${device.slice(1)}`)));

  if (mode === "code") {
    cv.code.textContent = item.code;
    return;
  }
  const frame = el("iframe", {
    class: `canvas-frame ${device === "desktop" ? "" : device}`,
    title: `Live preview: ${item.title}`,
    sandbox: "allow-scripts allow-modals allow-forms allow-popups",
    referrerpolicy: "no-referrer",
  });
  frame.srcdoc = buildSrcDoc(item.lang, item.code);
  cv.stage.replaceChildren(frame);
}

function showArtifacts(list, index = 0) {
  artifacts = list;
  current = Math.min(index, list.length - 1);
  mode = "preview";
  open("canvas");
  renderArtifact();
}

cv.select.addEventListener("change", () => { current = Number(cv.select.value); renderArtifact(); });
cv.preview.addEventListener("click", () => { mode = "preview"; renderArtifact(); });
cv.codeBtn.addEventListener("click", () => { mode = "code"; renderArtifact(); });
$("#devDesktop").addEventListener("click", () => { device = "desktop"; renderArtifact(); });
$("#devTablet").addEventListener("click", () => { device = "tablet"; renderArtifact(); });
$("#devPhone").addEventListener("click", () => { device = "phone"; renderArtifact(); });
$("#reloadBtn").addEventListener("click", renderArtifact);
$("#fullBtn").addEventListener("click", () => cv.stage.querySelector("iframe")?.requestFullscreen?.());
$("#copyCodeBtn").addEventListener("click", async () => {
  if (!artifacts[current]) return;
  await navigator.clipboard.writeText(artifacts[current].code);
  toast("Code copied");
});
$("#downloadBtn").addEventListener("click", () => {
  const item = artifacts[current];
  if (!item) return;
  const blob = new Blob([item.code], { type: "text/plain" });
  const link = el("a", { href: URL.createObjectURL(blob), download: `omnicanvas-${item.id}.${EXTENSIONS[item.lang] || "txt"}` });
  link.click();
  URL.revokeObjectURL(link.href);
});

/* ------------------------------------------------------------------- public */

export const lens = { open, close, toggle: () => (isOpen() ? close() : open()), isOpen, showSource, showArtifacts, setTab };

refreshSourceChrome();
renderArtifact();
