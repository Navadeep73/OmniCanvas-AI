/* md.js: markdown -> sanitized DOM, with code-block controls and citation chips. */

import { el, escapeHtml, icon } from "./core.js";

export const PREVIEWABLE = new Set(["html", "htm", "svg", "css", "javascript", "js", "jsx", "react", "mermaid"]);

const CITATION = /\[(S\d+(?:\s*[,;]\s*S\d+)*)\]/g;

function toHtml(text) {
  if (window.marked && window.DOMPurify) {
    const raw = window.marked.parse(text, { gfm: true, breaks: false });
    return window.DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  }
  // Offline fallback: still handles paragraphs, bold, inline code and fenced code.
  const inline = (t) =>
    escapeHtml(t)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
  return text
    .split(/(```[\w+-]*\n[\s\S]*?```)/g)
    .map((part) => {
      const fence = part.match(/^```([\w+-]*)\n([\s\S]*?)```$/);
      if (fence) return `<pre><code class="language-${fence[1] || "text"}">${escapeHtml(fence[2])}</code></pre>`;
      return part
        .split(/\n{2,}/)
        .filter((chunk) => chunk.trim())
        .map((chunk) => `<p>${inline(chunk)}</p>`)
        .join("");
    })
    .join("");
}

function decorateCode(container) {
  container.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    const match = code.className.match(/language-([\w+-]+)/);
    const lang = (match ? match[1] : "text").toLowerCase();

    if (window.hljs && window.hljs.getLanguage(lang)) {
      try { window.hljs.highlightElement(code); } catch { /* leave plain */ }
    }

    const actions = el("div", { class: "acts" });
    if (PREVIEWABLE.has(lang)) {
      actions.append(el("button", { class: "primary", "data-act": "preview", type: "button", text: "Open preview" }));
    }
    actions.append(el("button", { "data-act": "copy", type: "button", text: "Copy" }));

    const wrapper = el("div", { class: "codeblock", "data-lang": lang }, el("div", { class: "codeblock-head" }, el("span", { text: lang }), actions));
    pre.replaceWith(wrapper);
    wrapper.append(pre);
  });
}

function citationNodes(group, byRef) {
  const nodes = [];
  for (const ref of group.split(/[,;]/).map((s) => s.trim())) {
    const source = byRef.get(ref);
    if (source) {
      const range = source.page_end && source.page_end !== source.page ? `${source.page}-${source.page_end}` : source.page;
      nodes.push(
        el("button", {
          class: "cite",
          type: "button",
          "data-ref": ref,
          title: `${source.filename}, page ${range}`,
          "aria-label": `Open page ${source.page} of ${source.filename}`,
          text: `p.${source.page}`,
        })
      );
    } else {
      nodes.push(el("span", { class: "cite bad", title: "This tag doesn't match any retrieved passage", text: "?" }));
    }
  }
  return nodes;
}

function decorateCitations(container, sources) {
  const byRef = new Map(sources.map((s) => [s.ref, s]));
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.parentElement.closest("code, pre, a, button") || !node.nodeValue.includes("[S")
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });

  const targets = [];
  while (walker.nextNode()) targets.push(walker.currentNode);

  for (const node of targets) {
    const text = node.nodeValue;
    const fragment = document.createDocumentFragment();
    let last = 0;
    CITATION.lastIndex = 0;
    let match;
    while ((match = CITATION.exec(text))) {
      fragment.append(text.slice(last, match.index));
      fragment.append(...citationNodes(match[1], byRef));
      last = match.index + match[0].length;
    }
    fragment.append(text.slice(last));
    node.replaceWith(fragment);
  }
}

function decorateMisc(container) {
  container.querySelectorAll("p").forEach((p) => {
    const first = p.firstElementChild;
    if (first && first.tagName === "STRONG" && /^beyond your/i.test(first.textContent.trim())) {
      p.classList.add("beyond");
    }
  });
  container.querySelectorAll("a[href]").forEach((a) => {
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  });
}

/** Render markdown into `container`. `sources` resolve [S#] tags to page chips. */
export function renderMarkdown(container, text, { sources = [] } = {}) {
  container.classList.add("md");
  container.innerHTML = toHtml(text || "");
  decorateCode(container);
  decorateCitations(container, sources);
  decorateMisc(container);
}

/** Text suitable for read-aloud: no code, tags or markdown symbols. */
export function speakable(markdown) {
  return markdown
    .replace(/```[\s\S]*?```/g, " Code block omitted. ")
    .replace(/\[S\d+(?:\s*[,;]\s*S\d+)*\]/g, "")
    .replace(/[*_`#>|~-]{1,}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export { icon };
