/* chat.js: renders the conversation, including live streaming. */

import { $, announce, el, icon, toast } from "./core.js";
import { renderMarkdown, speakable } from "./md.js";

const feed = $("#feed");
const hero = $("#hero");
const thread = $("#thread");

const LANG_NAMES = { html: "interactive page", svg: "vector graphic", css: "style sheet", javascript: "script", jsx: "React component", mermaid: "diagram" };

function qualityChip(quality) {
  if (!quality || !quality.sources_retrieved || quality.groundedness == null) return null;
  const score = quality.groundedness;
  const percent = Math.round(score * 100);
  let label = "Well supported";
  let cls = "good";
  if (score < 0.5) { label = "Check this answer"; cls = "check"; }
  else if (score < 0.8) { label = "Partly supported"; cls = ""; }

  const lines = [`${percent}% of ${quality.claims_checked} checked statements match your document.`];
  (quality.unsupported || []).forEach((claim) => lines.push(`Not found in the sources: "${claim}"`));
  if (quality.invalid_citations?.length) lines.push(`Unknown source tags: ${quality.invalid_citations.join(", ")}`);
  if (quality.total_ms) lines.push(`Answered in ${(quality.total_ms / 1000).toFixed(1)}s.`);
  return el("span", { class: `quality ${cls}`, title: lines.join("\n"), text: label });
}

class AssistantMessage {
  constructor(view, { id = null, streaming = false } = {}) {
    this.view = view;
    this.text = "";
    this.sources = [];
    this.artifacts = [];
    this.raf = 0;

    this.mdEl = el("div", { class: "md" });
    this.notice = el("div", { class: "msg-notice", hidden: true });
    this.extras = el("div");
    this.body = el("div", { class: "msg-body" }, this.notice, this.mdEl, this.extras);
    this.root = el(
      "article",
      { class: `msg-ai${streaming ? " streaming" : ""}`, "data-id": id },
      el("div", { class: "mark" }, el("img", { src: "/assets/logo.svg", alt: "" })),
      this.body
    );
    this.root._msg = this;

    if (streaming) {
      this.thinking = el("div", { class: "thinking" }, el("i"), "Reading your question");
      this.mdEl.append(this.thinking);
    }
  }

  setMeta(meta) {
    this.sources = meta.sources || [];
    const tags = [];
    if (meta.pii_redacted?.length) tags.push(el("span", { class: "tag", text: "Personal details hidden" }));
    if (meta.blocked_passages) {
      tags.push(el("span", { class: "tag warn", text: `Ignored ${meta.blocked_passages} passage${meta.blocked_passages > 1 ? "s" : ""} that looked like instructions` }));
    }
    if (this.thinking) {
      this.thinking.lastChild.textContent = this.sources.length
        ? `Found ${this.sources.length} relevant passage${this.sources.length > 1 ? "s" : ""}`
        : "Thinking";
    }
    if (tags.length) {
      this.notice.hidden = false;
      this.notice.replaceChildren(...tags);
    }
  }

  push(piece) {
    this.text += piece;
    this.thinking = null;
    if (!this.raf) {
      this.raf = requestAnimationFrame(() => {
        this.raf = 0;
        this.#paint();
        this.view.stickToBottom();
      });
    }
  }

  #paint() {
    renderMarkdown(this.mdEl, this.text, { sources: this.sources });
  }

  finish({ sources, artifacts = [], quality = null, message_id = null } = {}, { allowRegenerate = true } = {}) {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    if (sources && !this.sources.length) this.sources = sources;
    this.artifacts = artifacts;
    this.root.classList.remove("streaming");
    if (message_id) this.root.dataset.id = message_id;
    this.#paint();

    // Code that became a live artifact is already in the Canvas; fold it away.
    artifacts.forEach((artifact) => {
      this.mdEl.querySelectorAll(".codeblock").forEach((block) => {
        if (block.querySelector("code").textContent.trim() !== artifact.code.trim()) return;
        block.classList.add("collapsed");
        block.querySelector(".acts").prepend(el("button", { type: "button", "data-act": "toggle", text: "Show code" }));
      });
    });

    this.extras.replaceChildren();
    artifacts.forEach((artifact, index) => {
      this.extras.append(
        el(
          "button",
          { class: "artifact-card", type: "button", "data-artifact": index },
          el("span", { class: "glyph", html: icon("layers") }),
          el("span", {}, el("strong", { text: artifact.title }), el("small", { text: `Live ${LANG_NAMES[artifact.lang] || artifact.lang}` })),
          el("span", { class: "go", text: "Open" })
        )
      );
    });

    const cited = sources || []; // the server only sends sources the answer actually cited
    if (cited.length) {
      const row = el("div", { class: "src-row" }, el("span", { class: "label", text: "Sources" }));
      const seen = new Set();
      cited.forEach((s) => {
        const key = `${s.doc_id}:${s.page}`;
        if (seen.has(key)) return;
        seen.add(key);
        row.append(el("button", { class: "cite", type: "button", "data-ref": s.ref, title: s.filename, text: `p.${s.page}` }));
      });
      this.extras.append(row);
    }

    const foot = el(
      "div",
      { class: "msg-foot" },
      el("button", { class: "icon-btn", "data-act": "copy", "aria-label": "Copy answer", title: "Copy", html: icon("copy") }),
      el("button", { class: "icon-btn", "data-act": "speak", "aria-label": "Read aloud", title: "Read aloud", html: icon("speaker") })
    );
    if (allowRegenerate) {
      foot.append(el("button", { class: "icon-btn", "data-act": "regen", "aria-label": "Regenerate answer", title: "Regenerate", html: icon("redo") }));
    }
    const chip = qualityChip(quality);
    if (chip) foot.append(chip);
    this.extras.append(foot);
  }

  fail(message) {
    this.root.classList.remove("streaming");
    this.mdEl.replaceChildren(el("p", { class: "beyond", text: message }));
  }

  get isEmpty() {
    return !this.text;
  }
}

export class ChatView {
  constructor({ onCite, onPreview, onArtifacts, onRegenerate }) {
    this.handlers = { onCite, onPreview, onArtifacts, onRegenerate };
    thread.addEventListener("click", (event) => this.#click(event));
  }

  get hasMessages() {
    return !thread.hidden && thread.children.length > 0;
  }

  showHero() {
    hero.hidden = false;
    thread.hidden = true;
    thread.replaceChildren();
  }

  #showThread() {
    hero.hidden = true;
    thread.hidden = false;
  }

  stickToBottom(force = false) {
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
    if (force || nearBottom) feed.scrollTo({ top: feed.scrollHeight, behavior: force ? "smooth" : "auto" });
  }

  removeLastAssistant() {
    const all = thread.querySelectorAll(".msg-ai");
    all[all.length - 1]?.remove();
  }

  clearRegenerate() {
    thread.querySelectorAll('[data-act="regen"]').forEach((b) => b.remove());
  }

  addUser(text, piiLabels = []) {
    this.#showThread();
    thread.append(el("div", { class: "msg-user", text }));
    if (piiLabels?.length) {
      thread.append(el("div", { class: "pii-note", html: `${icon("shield", "")}<span>Personal details were hidden before sending</span>` }));
    }
    this.stickToBottom(true);
  }

  beginAssistant() {
    this.#showThread();
    this.clearRegenerate();
    const message = new AssistantMessage(this, { streaming: true });
    thread.append(message.root);
    this.stickToBottom(true);
    return message;
  }

  renderHistory(messages) {
    thread.replaceChildren();
    if (!messages.length) return this.showHero();
    this.#showThread();
    messages.forEach((m, index) => {
      if (m.sender === "user") {
        thread.append(el("div", { class: "msg-user", text: m.content }));
        if (m.pii_labels?.length) {
          thread.append(el("div", { class: "pii-note", html: `${icon("shield")}<span>Personal details were hidden before sending</span>` }));
        }
      } else {
        const message = new AssistantMessage(this, { id: m.id });
        message.text = m.content;
        message.sources = m.sources || [];
        thread.append(message.root);
        const isLast = index === messages.length - 1;
        message.finish({ sources: m.sources || [], artifacts: m.artifacts || [], quality: m.quality }, { allowRegenerate: isLast });
      }
    });
    this.stickToBottom(true);
  }

  #click(event) {
    const target = event.target.closest("button");
    if (!target) return;
    const messageEl = target.closest(".msg-ai");
    const message = messageEl?._msg;

    if (target.matches(".cite[data-ref]") && message) {
      const source = message.sources.find((s) => s.ref === target.dataset.ref);
      if (source) this.handlers.onCite(source, target);
      return;
    }
    if (target.matches(".artifact-card") && message) {
      this.handlers.onArtifacts(message.artifacts, Number(target.dataset.artifact));
      return;
    }
    if (target.closest(".codeblock")) {
      const block = target.closest(".codeblock");
      const code = block.querySelector("code").textContent;
      if (target.dataset.act === "toggle") {
        const collapsed = block.classList.toggle("collapsed");
        target.textContent = collapsed ? "Show code" : "Hide code";
      } else if (target.dataset.act === "copy") {
        navigator.clipboard.writeText(code).then(() => {
          target.textContent = "Copied";
          setTimeout(() => (target.textContent = "Copy"), 1600);
        });
      } else if (target.dataset.act === "preview") {
        this.handlers.onPreview({ lang: block.dataset.lang, code });
      }
      return;
    }
    const act = target.dataset.act;
    if (act === "copy" && message) {
      navigator.clipboard.writeText(message.text).then(() => toast("Answer copied"));
    } else if (act === "speak" && message) {
      if (window.speechSynthesis?.speaking) {
        window.speechSynthesis.cancel();
      } else if (window.speechSynthesis) {
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(speakable(message.text)));
      } else {
        toast("Read aloud isn't supported in this browser.", { error: true });
      }
    } else if (act === "regen") {
      this.handlers.onRegenerate();
    }
  }

  announceDone() {
    announce("Answer ready");
  }
}
