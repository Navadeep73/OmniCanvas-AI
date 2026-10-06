/* palette.js: Ctrl/Cmd+K command palette with simple fuzzy matching. */

import { $, el } from "./core.js";

const root = $("#palette");
const input = $("#paletteInput");
const list = $("#paletteList");

let commands = [];
let results = [];
let selected = 0;

function score(query, text) {
  if (!query) return 1;
  const haystack = text.toLowerCase();
  let position = 0;
  let total = 0;
  for (const char of query.toLowerCase()) {
    const found = haystack.indexOf(char, position);
    if (found === -1) return 0;
    total += found === position ? 3 : 1; // reward consecutive characters
    position = found + 1;
  }
  return total;
}

function draw() {
  list.replaceChildren(
    ...results.map((command, index) =>
      el(
        "li",
        { role: "option", "aria-selected": String(index === selected), "data-index": index },
        el("span", { class: "grow", text: command.label }),
        command.hint ? el("kbd", { text: command.hint }) : null
      )
    )
  );
  if (!results.length) list.append(el("li", { text: "No matching command" }));
}

function filter() {
  const query = input.value.trim();
  results = commands
    .map((command) => ({ command, value: score(query, command.label) }))
    .filter((entry) => entry.value > 0)
    .sort((a, b) => b.value - a.value)
    .map((entry) => entry.command);
  selected = 0;
  draw();
}

function run(index) {
  const command = results[index];
  if (!command) return;
  close();
  command.run();
}

export function open() {
  root.hidden = false;
  input.value = "";
  filter();
  input.focus();
}

export function close() {
  root.hidden = true;
}

input.addEventListener("input", filter);
input.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") { event.preventDefault(); selected = Math.min(selected + 1, results.length - 1); draw(); }
  else if (event.key === "ArrowUp") { event.preventDefault(); selected = Math.max(selected - 1, 0); draw(); }
  else if (event.key === "Enter") { event.preventDefault(); run(selected); }
  else if (event.key === "Escape") { event.preventDefault(); close(); }
});
list.addEventListener("click", (event) => {
  const item = event.target.closest("li[data-index]");
  if (item) run(Number(item.dataset.index));
});
root.addEventListener("mousedown", (event) => {
  if (event.target === root) close();
});

export const palette = {
  register(next) { commands = next; },
  open,
  close,
  isOpen: () => !root.hidden,
};
