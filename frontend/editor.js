// CodeMirror 6 wrapper for the leela IDE.
//
// Bundled to ../static/lee-cm6.js and committed, so the IDE works offline and a
// user installing from PyPI never needs node. Rebuild with `npm run build`.
//
// The page talks to this through one small surface (`window.LeeCM`) rather than
// importing CodeMirror itself, so the keymap that Python owns stays the single
// source of truth: `create()` takes the bindings it should honour, and anything
// it does not recognise is left to bubble up to the document handler.

import {EditorState, Compartment, StateEffect, StateField, Prec, RangeSet} from "@codemirror/state";
import {EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter,
        drawSelection, rectangularSelection, crosshairCursor, Decoration, WidgetType,
        gutter, GutterMarker, placeholder as cmPlaceholder, ViewPlugin, highlightSpecialChars} from "@codemirror/view";
import {defaultKeymap, history, historyKeymap, indentWithTab,
        undo as cmUndo, redo as cmRedo,
        indentMore as cmIndentMore, indentLess as cmIndentLess,
        indentSelection as cmIndentSelection} from "@codemirror/commands";
import {searchKeymap, highlightSelectionMatches, openSearchPanel} from "@codemirror/search";
import {autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap,
        startCompletion as cmStartCompletion} from "@codemirror/autocomplete";
import {syntaxHighlighting, HighlightStyle, indentUnit, bracketMatching,
        foldGutter, foldKeymap, indentOnInput, StreamLanguage, syntaxTree} from "@codemirror/language";
import {linter, forEachDiagnostic} from "@codemirror/lint";
import {tags as t} from "@lezer/highlight";
import {MergeView} from "@codemirror/merge";

import {python} from "@codemirror/lang-python";
import {markdown} from "@codemirror/lang-markdown";
import {javascript} from "@codemirror/lang-javascript";
import {json} from "@codemirror/lang-json";
import {html} from "@codemirror/lang-html";
import {css} from "@codemirror/lang-css";
import {sql} from "@codemirror/lang-sql";
import {yaml} from "@codemirror/lang-yaml";
import {cpp} from "@codemirror/lang-cpp";
import {go} from "@codemirror/lang-go";
import {java} from "@codemirror/lang-java";
import {rust} from "@codemirror/lang-rust";
import {xml} from "@codemirror/lang-xml";
import {toml} from "@codemirror/legacy-modes/mode/toml";
import {shell} from "@codemirror/legacy-modes/mode/shell";
import {properties} from "@codemirror/legacy-modes/mode/properties";

// Language ids match leela.fs.LANGS, so Python decides the mode and both
// frontends resolve the same name.
const LANGS = {
  python, markdown, javascript, json, html, css, sql, yaml, cpp, go, java, rust, xml,
  typescript: () => javascript({typescript: true}),
  jsx: () => javascript({jsx: true}),
  tsx: () => javascript({jsx: true, typescript: true}),
  toml: () => StreamLanguage.define(toml),
  bash: () => StreamLanguage.define(shell),
  properties: () => StreamLanguage.define(properties),
};

// Colours are CSS custom properties, not literals, so the editor follows the
// app's theme (and its light/dark switch) instead of carrying its own palette.
const v = (n, fallback) => `var(--lee-${n}, ${fallback})`;

const theme = EditorView.theme({
  "&": {color: v("fg", "#c9d1d9"), backgroundColor: "transparent", height: "100%"},
  ".cm-content": {caretColor: v("accent", "#58a6ff"), fontFamily: v("mono", "ui-monospace, monospace"),
                  fontSize: v("code-size", "13px"), padding: "4px 0"},
  ".cm-cursor, .cm-dropCursor": {borderLeftColor: v("accent", "#58a6ff"), borderLeftWidth: "2px"},
  "&.cm-focused": {outline: "none"},
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground":
    {backgroundColor: v("sel", "#264f78")},
  ".cm-content ::selection":
    {backgroundColor: v("sel", "#264f78"), color: v("selection-fg", "#f0f6fc")},
  ".cm-gutters": {backgroundColor: "transparent", color: v("fg4", "#6e7681"), border: "none",
                  fontSize: v("code-size", "13px")},
  ".cm-activeLine": {backgroundColor: v("active-line", "rgba(255,255,255,.04)")},
  ".cm-activeLineGutter": {backgroundColor: "transparent", color: v("fg2", "#8b949e")},
  ".cm-matchingBracket, &.cm-focused .cm-matchingBracket":
    {backgroundColor: v("bracket", "rgba(88,166,255,.25)"), outline: "none"},
  ".cm-tooltip": {backgroundColor: v("bg1", "#161b22"), border: `1px solid ${v("border", "#30363d")}`,
                  borderRadius: "4px", color: v("fg", "#c9d1d9")},
  ".cm-tooltip-autocomplete ul li[aria-selected]":
    {backgroundColor: v("accent", "#58a6ff"), color: v("bg", "#0d1117")},
  ".cm-placeholder": {color: v("fg4", "#6e7681"), fontStyle: "italic"},
  ".cm-scroller": {overflow: "auto", lineHeight: "1.5"},
  ".cm-lee-ghost": {color: v("fg4", "#6e7681"), fontStyle: "italic", opacity: ".8"},
}, {dark: true});

const hl = HighlightStyle.define([
  {tag: [t.keyword, t.moduleKeyword, t.controlKeyword], color: v("red", "#ff7b72")},
  {tag: [t.string, t.special(t.string)], color: v("green", "#a5d6ff")},
  {tag: [t.number, t.bool, t.null], color: v("purple", "#79c0ff")},
  {tag: [t.comment, t.lineComment, t.blockComment], color: v("fg4", "#8b949e"), fontStyle: "italic"},
  {tag: [t.function(t.variableName), t.function(t.propertyName)], color: v("blue", "#d2a8ff")},
  {tag: [t.definition(t.variableName), t.definition(t.propertyName)], color: v("orange", "#ffa657")},
  {tag: [t.className, t.typeName, t.namespace], color: v("yellow", "#ffa657")},
  {tag: [t.operator, t.operatorKeyword], color: v("aqua", "#79c0ff")},
  {tag: [t.propertyName, t.attributeName], color: v("aqua", "#79c0ff")},
  {tag: [t.heading], color: v("blue", "#d2a8ff"), fontWeight: "bold"},
  {tag: [t.link, t.url], color: v("aqua", "#79c0ff"), textDecoration: "underline"},
  {tag: [t.emphasis], fontStyle: "italic"},
  {tag: [t.strong], fontWeight: "bold"},
  {tag: [t.invalid], color: v("red", "#ff7b72")},
]);

// Typing happens one key at a time: selecting `'''` and typing `"""` first sends a
// single `"`, so a transaction filter alone never sees the intended triple delimiter.
// Intercept that first quote and make the complete paired edit as one undoable transaction.
const pairedTripleQuoteInput = EditorView.inputHandler.of((view, from, to, text) => {
  if (from === to || (text !== "'" && text !== '\"')) return false;
  const old = view.state.doc.sliceString(from, to), n = old.length;
  if (![1, 3].includes(n) || !["'", '\"'].includes(old[0]) || old !== old[0].repeat(n) || text === old[0]) return false;
  const next = text.repeat(n), tail = view.state.doc.sliceString(to), at = tail.indexOf(old);
  if (at < 0) return false;
  const close = to + at;
  view.dispatch({changes: [{from, to, insert: next}, {from: close, to: close + n, insert: next}],
                 selection: {anchor: from + n}, userEvent: "input.type"});
  return true;
});

// Paste/programmatic replacements arrive as one full change, so retain the transaction
// path as well. Ordinary one-character quote edits remain untouched.
const pairedTripleQuotes = EditorState.transactionFilter.of(tr => {
  if (!tr.docChanged || tr.startState.selection.ranges.length !== 1) return tr;
  const sel = tr.startState.selection.main;
  if (sel.empty) return tr;
  const old = tr.startState.doc.sliceString(sel.from, sel.to);
  if (!["'", '\"', "'''", '\"\"\"'].includes(old)) return tr;
  let inserted = null;
  tr.changes.iterChanges((from, to, _a, _b, text) => {
    if (from === sel.from && to === sel.to) inserted = text.toString();
  });
  const replacement = old[0] === "'" ? '\"'.repeat(old.length) : "'".repeat(old.length);
  if (inserted !== replacement) return tr;
  const tail = tr.startState.doc.sliceString(sel.to), at = tail.indexOf(old);
  if (at < 0) return tr;
  const close = sel.to + at;
  return [tr, {changes: {from: close, to: close + old.length, insert: inserted}, sequential: true}];
});

function langExt(name) {
  const f = LANGS[name];
  return f ? f() : [];
}

// CodeMirror supplies the diagnostic UI (squiggles, hover text and severity
// colours); the source depends on the language. Lezer's recovery nodes give every
// bundled parser immediate syntax errors. Python additionally asks the local server
// to run the standard compiler, which gives useful messages and SyntaxWarnings
// without executing the buffer or requiring a third-party linter.
function parserDiagnostics(view) {
  const diagnostics = [], seen = new Set(), doc = view.state.doc;
  syntaxTree(view.state).iterate({enter(node) {
    if (!node.type.isError) return;
    let from = node.from, to = node.to;
    if (to <= from) {
      if (from < doc.length) to = from + 1;
      else if (from) from -= 1;
    }
    const key = `${from}:${to}`;
    if (!seen.has(key)) {
      seen.add(key);
      diagnostics.push({from, to, severity: "error", message: "Invalid or incomplete syntax", source: "parser"});
    }
    return false;
  }});
  return diagnostics;
}

function serverDiagnostics(endpoint, lang, path = "") {
  return async view => {
    try {
      const response = await fetch(endpoint, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({code: view.state.doc.toString(), lang, path}),
      });
      if (!response.ok) return [];
      const data = await response.json(), length = view.state.doc.length;
      return (data.diagnostics || []).map(item => ({
        ...item,
        from: Math.max(0, Math.min(Number(item.from) || 0, length)),
        to: Math.max(0, Math.min(Number(item.to) || 0, length)),
      })).filter(item => item.to >= item.from);
    } catch (_) { return []; }
  };
}

function lintExt(lang, readOnly, endpoint, path = "") {
  if (readOnly || !lang) return [];
  const source = ["python", "markdown"].includes(lang) && endpoint ? serverDiagnostics(endpoint, lang, path) : parserDiagnostics;
  return linter(source, {delay: 400});
}

function changeDecorations(doc, ranges) {
  const marks = [];
  for (const item of (ranges || [])) {
    const from = Math.max(1, Math.min(Number(item.from) || 1, doc.lines));
    const to = Math.max(from, Math.min(Number(item.to) || from, doc.lines));
    for (let n = from; n <= to; n++) marks.push(Decoration.line({
      class: `cm-lee-change cm-lee-change-${item.kind || "modified"}`,
      attributes: {"data-change-line": String(n)},
    }).range(doc.line(n).from));
  }
  return Decoration.set(marks, true);
}

// A completion source backed by the kernel's /complete contract, so completions
// come from the real namespace (venv modules included)
// rather than from a static word list.
function kernelCompletions(endpoint) {
  return async (ctx) => {
    const word = ctx.matchBefore(/[\w.]+/);
    if (!word && !ctx.explicit) return null;
    const pos = ctx.pos, doc = ctx.state.doc.toString();
    let res;
    try {
      const r = await fetch(`${endpoint}?pos=${pos}`,
        {method: "POST", headers: {"Content-Type": "application/json"},
         body: JSON.stringify({code: doc, pos})});
      if (!r.ok) return null;
      res = await r.json();
    } catch (e) { return null; }
    const matches = res.matches || [];
    if (!matches.length) return null;
    return {from: res.from ?? (word ? word.from : pos),
            options: matches.map(m => ({label: m, type: "variable"})),
            validFor: /^[\w.]*$/};
  };
}

// ---------------------------------------------------------------------------
// ghost text: the model's suggestion, shown but not yet in the document
//
// A suggestion is not an edit until it is accepted, so it lives in a StateField
// as a widget decoration rather than as inserted-then-maybe-deleted text. That
// distinction is the whole feature: undo history stays clean, `getDoc` never
// returns something the user did not write, and a save mid-suggestion cannot
// write the model's guess to disk.
// ---------------------------------------------------------------------------
const setGhostEffect = StateEffect.define();
const setInlineEffect = StateEffect.define();
const setChangesEffect = StateEffect.define();
const setBreakpointsEffect = StateEffect.define();
const setDebugLineEffect = StateEffect.define();
const setPackagesEffect = StateEffect.define();
const setInlayHintsEffect = StateEffect.define();

class GhostWidget extends WidgetType {
  constructor(text) { super(); this.text = text; }
  eq(other) { return other.text === this.text; }
  toDOM() {
    const w = document.createElement("span");
    w.className = "cm-lee-ghost";
    // One inline widget has to carry a multi-line suggestion, so newlines become <br>
    this.text.split("\n").forEach((l, i) => {
      if (i) w.appendChild(document.createElement("br"));
      w.appendChild(document.createTextNode(l));
    });
    return w;
  }
  ignoreEvent() { return false; }
}

const NO_GHOST = {text: "", pos: 0, deco: Decoration.none};

class InlineValueWidget extends WidgetType {
  constructor(item) { super(); this.item = item; }
  eq(other) {
    return other.item.name === this.item.name && other.item.value === this.item.value &&
           other.item.type === this.item.type;
  }
  toDOM() {
    const w = document.createElement("button");
    w.type = "button"; w.className = "cm-lee-inline-value";
    w.title = `${this.item.name}: click for the kernel value`;
    w.setAttribute("aria-label", `${this.item.name}, inspect runtime value`);
    const name = document.createElement("span"); name.className = "name";
    name.textContent = this.item.name;
    w.append(name);
    w.onclick = e => {
      e.preventDefault(); e.stopPropagation();
      window.dispatchEvent(new CustomEvent("lee-inline-open", {detail: {item: this.item, anchor: w}}));
    };
    return w;
  }
  ignoreEvent() { return false; }
}

class PackageVersionWidget extends WidgetType {
  constructor(item) { super(); this.item = item; }
  eq(other) { return JSON.stringify(other.item) === JSON.stringify(this.item); }
  toDOM() {
    const b = document.createElement("button"), installed = this.item.installed;
    b.type = "button";
    b.className = "cm-lee-package " + (installed == null ? "missing" : this.item.compatible === false ? "mismatch" : "installed");
    b.textContent = installed == null ? "not installed" : installed;
    const required = this.item.required ? ` ${this.item.required}` : "";
    b.title = `${this.item.name}${required}\n${installed == null ? "Not installed" : `Installed ${installed}`}\n${this.item.python}`;
    b.setAttribute("aria-label", `${this.item.name}, ${b.textContent}`);
    b.onclick = e => {
      e.preventDefault(); e.stopPropagation();
      window.dispatchEvent(new CustomEvent("lee-package-open", {detail: {item: this.item, anchor: b}}));
    };
    return b;
  }
  ignoreEvent() { return false; }
}

class InlayHintWidget extends WidgetType {
  constructor(item){super();this.item=item;}
  eq(other){return JSON.stringify(other.item)===JSON.stringify(this.item);}
  toDOM(){const span=document.createElement('span');span.className='cm-lee-inlay-hint';
    span.textContent=Array.isArray(this.item.label)?this.item.label.map(x=>x.value).join(''):String(this.item.label||'');
    if(this.item.tooltip)span.title=typeof this.item.tooltip==='string'?this.item.tooltip:(this.item.tooltip.value||'');return span;}
  ignoreEvent(){return true;}
}
const inlayHintField=StateField.define({create:()=>Decoration.none,update(hints,tr){hints=hints.map(tr.changes);
  if(tr.docChanged)hints=Decoration.none;for(const effect of tr.effects)if(effect.is(setInlayHintsEffect)){
    const ranges=(effect.value||[]).map((item,index)=>{const p=item.position||{},line=tr.state.doc.line(Math.max(1,Math.min((Number(p.line)||0)+1,tr.state.doc.lines))),
      column=Math.max(0,Math.min(Number(p.character)||0,line.length));return Decoration.widget({widget:new InlayHintWidget(item),side:1+index}).range(line.from+column);});
    hints=Decoration.set(ranges,true);}return hints;},provide:f=>EditorView.decorations.from(f)});

const packageField = StateField.define({
  create: () => Decoration.none,
  update(pills, tr) {
    pills = pills.map(tr.changes);
    if (tr.docChanged) pills = Decoration.none;
    for (const e of tr.effects) {
      if (!e.is(setPackagesEffect)) continue;
      const ranges = (e.value || []).map((item, index) => {
        const line = tr.state.doc.line(Math.max(1, Math.min(Number(item.line) || 1, tr.state.doc.lines)));
        const column = Math.max(0, Math.min(Number(item.column) || line.length, line.length));
        return Decoration.widget({widget: new PackageVersionWidget(item), side: 2 + index}).range(line.from + column);
      });
      pills = Decoration.set(ranges, true);
    }
    return pills;
  },
  provide: f => EditorView.decorations.from(f),
});

export function setPackageVersions(view, rows) {
  view.dispatch({effects: setPackagesEffect.of(rows || [])});
}
export function setInlayHints(view, rows) {
  view.dispatch({effects: setInlayHintsEffect.of(rows || [])});
}

class BreakpointMarker extends GutterMarker {
  toDOM() { const dot = document.createElement("span"); dot.className = "cm-lee-breakpoint"; return dot; }
}
const breakpointMarker = new BreakpointMarker();
const breakpointField = StateField.define({
  create: () => new Set(),
  update(lines, tr) {
    if (tr.docChanged) lines = new Set([...lines].filter(n => n <= tr.state.doc.lines));
    for (const e of tr.effects) if (e.is(setBreakpointsEffect)) lines = new Set(e.value || []);
    return lines;
  },
});
const breakpointGutter = onToggle => gutter({
  class: "cm-lee-breakpoints",
  markers: view => {
    const lines = view.state.field(breakpointField, false) || new Set(), ranges = [];
    for (const n of lines) if (n >= 1 && n <= view.state.doc.lines)
      ranges.push(breakpointMarker.range(view.state.doc.line(n).from));
    return RangeSet.of(ranges, true);
  },
  initialSpacer: () => breakpointMarker,
  domEventHandlers: {mousedown(view, line) {
    const lines = new Set(view.state.field(breakpointField, false) || []);
    const n = view.state.doc.lineAt(line.from).number;
    if (lines.has(n)) lines.delete(n); else lines.add(n);
    view.dispatch({effects: setBreakpointsEffect.of([...lines])});
    if (onToggle) onToggle([...lines].sort((a, b) => a - b));
    return true;
  }},
});

export function setBreakpoints(view, lines) {
  view.dispatch({effects: setBreakpointsEffect.of(lines || [])});
}

const debugLineField = StateField.define({
  create: () => Decoration.none,
  update(mark, tr) {
    mark = mark.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setDebugLineEffect)) continue;
      const line = Number(e.value) || 0;
      mark = line >= 1 && line <= tr.state.doc.lines
        ? Decoration.set([Decoration.line({class: "cm-lee-debug-line"}).range(tr.state.doc.line(line).from)])
        : Decoration.none;
    }
    return mark;
  },
  provide: f => EditorView.decorations.from(f),
});

export function setDebugLine(view, line) {
  view.dispatch({effects: setDebugLineEffect.of(Number(line) || 0)});
}

const changesField = StateField.define({
  create: () => Decoration.none,
  update(marks, tr) {
    marks = marks.map(tr.changes);
    for (const e of tr.effects) if (e.is(setChangesEffect)) marks = changeDecorations(tr.state.doc, e.value);
    return marks;
  },
  provide: f => EditorView.decorations.from(f),
});

export function setChangedLines(view, ranges) {
  view.dispatch({effects: setChangesEffect.of(ranges || [])});
}

const inlineField = StateField.define({
  create: () => Decoration.none,
  update(values, tr) {
    // Values describe the exact source that ran. The first edit invalidates them rather
    // than letting a convincing but stale result sit beside changed code.
    if (tr.docChanged) values = Decoration.none;
    for (const e of tr.effects) {
      if (!e.is(setInlineEffect)) continue;
      const byLine = new Map();
      for (const item of (e.value || [])) {
        const line = Math.max(1, Math.min(Number(item.line) || 1, tr.state.doc.lines));
        if (!byLine.has(line)) byLine.set(line, []);
        byLine.get(line).push(item);
      }
      const ranges = [];
      for (const [lineNo, items] of byLine) {
        const line = tr.state.doc.line(lineNo);
        items.forEach((item, i) => ranges.push(Decoration.widget({
          widget: new InlineValueWidget(item), side: 1 + i,
        }).range(line.to)));
      }
      values = Decoration.set(ranges, true);
    }
    return values;
  },
  provide: f => EditorView.decorations.from(f),
});

export function setInlineValues(view, values) {
  view.dispatch({effects: setInlineEffect.of(values || [])});
}

const ghostField = StateField.define({
  create: () => NO_GHOST,
  update(g, tr) {
    for (const e of tr.effects) {
      if (!e.is(setGhostEffect)) continue;
      if (!e.value || !e.value.text) return NO_GHOST;
      const {text, pos} = e.value;
      return {text, pos, deco: Decoration.set(
        [Decoration.widget({widget: new GhostWidget(text), side: 1}).range(pos)])};
    }
    // Any edit or cursor move invalidates it: the suggestion was written for a
    // cursor that is no longer where it was asked about.
    if (g.text && (tr.docChanged || tr.selection)) return NO_GHOST;
    return g;
  },
  provide: (f) => EditorView.decorations.from(f, (g) => g.deco),
});

export const ghost = (view) => (view.state.field(ghostField, false) || NO_GHOST).text;

export function setGhost(view, text) {
  view.dispatch({effects: setGhostEffect.of(
    text ? {text, pos: view.state.selection.main.head} : null)});
}

export function acceptGhost(view) {
  const g = view.state.field(ghostField, false);
  if (!g || !g.text) return false;               // nothing pending: let Tab indent as usual
  view.dispatch({changes: {from: g.pos, insert: g.text},
                 selection: {anchor: g.pos + g.text.length},
                 effects: setGhostEffect.of(null)});
  return true;
}

export const clearGhost = (view) => setGhost(view, "");

// Tab accepts, escape dismisses -- and both fall through when nothing is pending,
// so indent and CodeMirror's own escape behaviour are untouched the rest of the time.
const ghostKeymap = Prec.highest(keymap.of([
  {key: "Tab", run: acceptGhost},
  {key: "Escape", run: (v) => (ghost(v) ? (clearGhost(v), true) : false)},
]));
function bindFind(view) {
  view.contentDOM.addEventListener("keydown", event => {
    if (event.key.toLowerCase() !== "f" || event.altKey || event.shiftKey || !(event.metaKey || event.ctrlKey)) return;
    event.preventDefault(); event.stopPropagation(); openSearchPanel(view);
  });
}

// Turn the Python-side chord table into CodeMirror bindings. Anything the app
// did not ask for is not bound here at all, so it reaches the document handler.
function appKeymap(binds) {
  return (binds || []).map(b => ({
    key: b.cm,
    preventDefault: true,
    run: () => { b.run(); return true; },
  }));
}

const OVERVIEW_W = 14;

/* The overview stripe: the scrollbar, marked up.

   It replaced a compressed picture of the text, which was 72px of unreadable grey that
   answered no question anyone had -- you cannot read it, and the thing you actually want
   from a full-file view is *where the problems and the changes are*, which a picture of the
   letters cannot tell you. So the stripe carries the two things worth seeing at file scale:
   a tick across it for each diagnostic, and a bar down its edge for each uncommitted line.

   It is the scroll bar rather than a panel beside one. The native bar is hidden while it is
   shown and this takes over the job, so it never becomes a second thing to scroll -- there
   is one document and one place that says where you are in it.

   Whose bar, though: CodeMirror usually scrolls itself and in leela it does not -- `.cm-editor`
   is laid out at the height of the whole file inside `.lee-editor`. Measuring `view.dom` therefore
   measured the document, and the stripe came out a 14px canvas thousands of pixels tall. */
/* Vertical overflow measured against the border box rather than `clientHeight`.

   `clientHeight` excludes a horizontal scroll bar, and hiding one is exactly what this stripe
   does: `has-overview` sets `scrollbar-width: none`. So a pane overflowing by less than a bar's
   thickness said "overflowing", got the class, grew its own `clientHeight` by the thickness of the
   bar that just went away, and said "not overflowing" on the next frame. The border box does not
   move when a bar inside it is drawn or not, so the answer stops depending on the answer. A code
   cell is where this bit: long lines give it the horizontal bar, and an agent pane streaming
   tokens re-measures every frame. */
const OVER_SHOW = 24, OVER_HIDE = 8;
const overflowsDown = (el, shown = false) => {
  const box = el.getBoundingClientRect().height;
  // Hysteresis, now that the measure itself holds still: rendered markdown settles over several
  // frames as its images and fonts arrive, and content that lands within a few pixels of the
  // threshold was appearing and disappearing with it.
  return box > 0 && el.scrollHeight > box + (shown ? OVER_HIDE : OVER_SHOW);
};

/* `has-overview`, with the width the hidden bar was taking held back as padding.

   A scroll bar takes layout space wherever the platform draws it in the flow rather than over the
   content: macOS with "Show scroll bars: Always", and every Windows and Linux desktop. Hiding it
   hands that width to the text, wrapped text rewraps, and `scrollHeight` moves. That is the same
   number the stripe decides on, so the class fed itself: the stripe appeared, the pane got wider
   and shorter, it fell under the threshold, the stripe went, the bar came back, and it flickered
   at frame rate. The rewrap is worth hundreds of pixels where a line sits near a wrap boundary,
   so no hysteresis narrower than a paragraph would have held it.

   The bar's thickness is measured, not assumed: it is zero where the platform draws overlay bars,
   and that reserves nothing.

   `by` names the stripe asking, and the pane counts them, because several reach the same pane and
   they do not agree. A file's stripe scrolls `#editor` and so does a notebook's, and the notebook
   painter asserted "off" on every scroll of any tab: it took the class back off under a file's
   stripe, which drew on regardless, and the bar returned beside it. Editors do it to each other
   too. Every editor in one scrolling panel resolves to that panel, and `overviewMode: 'long'` means
   a short one says "off" about the very pane a long one beside it is drawing over. Naming the kind
   was not enough, because both are `cm`. So the pane holds the set of stripes that want its bar
   gone, and gives it back when the last of them leaves. */
export function overviewGutter(el, on, by = 'cm') {
  if (!el) return;
  const held = new Set((el.dataset.leeOverview || '').split(' ').filter(Boolean));
  on ? held.add(by) : held.delete(by);
  if (held.size) el.dataset.leeOverview = [...held].join(' '); else delete el.dataset.leeOverview;
  if (el.classList.contains('has-overview') === (held.size > 0)) return;
  if (!held.size) {
    el.classList.remove('has-overview');
    el.style.paddingRight = el.dataset.leeGutter || '';
    delete el.dataset.leeGutter;
    return;
  }
  const css = getComputedStyle(el);
  const bar = el.offsetWidth - el.clientWidth -
              parseFloat(css.borderLeftWidth) - parseFloat(css.borderRightWidth);
  el.dataset.leeGutter = el.style.paddingRight;
  el.classList.add('has-overview');
  if (bar > .5) el.style.paddingRight = (parseFloat(css.paddingRight) + bar) + 'px';
}

// The element that really scrolls: CodeMirror's own, or the pane it is laid out inside. Never the
// document: in a browser it overflows where the app window does not, and `has-overview` on `<body>`
// matches no rule, so the bar it was meant to hide stayed put.
function scrollerFor(view) {
  for (let el = view.scrollDOM; el && el !== document.body; el = el.parentElement) {
    if (overflowsDown(el)) return el;
  }
  return view.scrollDOM;
}

let overviewSeq = 0;
function overviewPlugin(mode = 'off', threshold = 120) {
  return ViewPlugin.fromClass(class {
    constructor(view) {
      this.view = view;
      // Its own name, not the kind's: a panel of editors all claim the panel, and one of them
      // saying "off" must not speak for the rest.
      this.gutter = 'cm' + (++overviewSeq);
      this.dom = document.createElement('canvas'); this.dom.className = 'cm-lee-overview';
      this.dom.setAttribute('aria-label', 'overview: diagnostics and uncommitted lines');
      view.dom.appendChild(this.dom);
      const drag = e => { if (e.buttons & 1) { e.preventDefault(); this.seek(e); } };
      this.dom.addEventListener('pointerdown', e => {
        this.dom.setPointerCapture(e.pointerId); e.preventDefault(); this.seek(e);
      });
      this.dom.addEventListener('pointermove', drag);
      // An outer pane scrolling is not a transaction, so nothing else would redraw or move it.
      this.frame = 0; this.scroller = null;
      this.queue = () => {
        cancelAnimationFrame(this.frame);
        this.frame = requestAnimationFrame(() => this.draw());
      };
      /* Resize arrives in bursts: a splitter drag changes the pane's width at pointer rate, and
         each of those would redraw every mounted editor's canvas. One draw once it settles. A
         scroll still redraws on the next frame, because there the stripe is the thumb. */
      this.settle = 0;
      this.later = () => { clearTimeout(this.settle); this.settle = setTimeout(this.queue, 90); };
      addEventListener('scroll', this.queue, true);
      // Moving a panel resizes the pane that scrolls without scrolling it, changing the document,
      // or touching CodeMirror's geometry, so none of the above fires and the stripe kept its old
      // position and height: a leftover scroll bar stranded wherever the pane used to be.
      this.ro = new ResizeObserver(() => this.later());
      this.observed = null;
      this.draw();
    }
    update(u) {
      // Diagnostics and change marks both arrive as effects on a transaction that touches
      // neither the document nor the viewport, so those alone are not enough to redraw on.
      if (u.docChanged || u.viewportChanged || u.geometryChanged ||
          u.transactions.some(tr => tr.effects.length)) this.draw();
    }
    seek(e) {
      // The clicked fraction of the file becomes the middle of the viewport -- the same
      // gesture whether you are dragging the thumb or jumping to a mark you spotted.
      const box = this.dom.getBoundingClientRect(), s = this.scroller || this.view.scrollDOM;
      const at = Math.max(0, Math.min(1, (e.clientY - box.top) / (box.height || 1)));
      s.scrollTop = Math.max(0, at * s.scrollHeight - s.clientHeight / 2);
    }
    colour(name, fallback) {
      const v = getComputedStyle(this.view.dom).getPropertyValue(name).trim();
      return v || fallback;
    }
    // Redraw when either the editor or the element that scrolls it changes size.
    watch(scroller) {
      if (this.observed === scroller) return;
      this.observed = scroller;
      this.ro.disconnect();
      this.ro.observe(this.view.dom);                    // never `this.dom`: drawing resizes that
      if (scroller !== this.view.scrollDOM) this.ro.observe(scroller);
    }
    draw() {
      const doc = this.view.state.doc, lines = doc.lines;
      const previous = this.scroller;
      const scroller = this.scroller = scrollerFor(this.view);
      // The pane that scrolls can change when panels move. The old one keeps `has-overview`, and
      // with it a hidden native scroll bar, unless it is cleared here.
      if (previous && previous !== scroller) overviewGutter(previous, false, this.gutter);
      this.watch(scroller);
      const shown = (mode === 'always' || (mode === 'long' && lines >= threshold)) &&
                    overflowsDown(scroller, this.dom.hidden === false);
      this.dom.hidden = !shown;
      this.view.dom.classList.toggle('cm-lee-has-overview', shown);
      // `has-overview` is the notebook stripe's class, hiding the bar of the pane that scrolls.
      // CodeMirror's own scroller is not given it: `.cm-lee-has-overview .cm-scroller` reserves the
      // stripe's 15px there, which is already at least what a bar in the flow was taking.
      if (scroller !== this.view.scrollDOM) overviewGutter(scroller, shown, this.gutter);
      if (!shown) return;
      const dpr = devicePixelRatio || 1, w = OVERVIEW_W, h = Math.max(40, scroller.clientHeight);
      this.dom.width = w * dpr; this.dom.height = h * dpr;
      this.dom.style.width = w + 'px'; this.dom.style.height = h + 'px';
      // Absolute inside a document-tall editor: put it at the scrollport's top, measured
      // against the editor's. Zero whenever CodeMirror scrolls itself.
      this.dom.style.top = (scroller === this.view.scrollDOM ? 0 :
        scroller.getBoundingClientRect().top - this.view.dom.getBoundingClientRect().top) + 'px';
      const ctx = this.dom.getContext('2d'); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
      const y = n => (n - 1) / Math.max(1, lines) * h;

      // Uncommitted lines, down the inner edge: the same colours the lines themselves carry.
      const changes = {modified: this.colour('--lee-orange', '#d29922'),
                       added: this.colour('--lee-green', '#3fb950'),
                       deleted: this.colour('--lee-red', '#f85149')};
      const marks = this.view.state.field(changesField, false);
      if (marks) marks.between(0, doc.length, (from, to, deco) => {
        const kind = /cm-lee-change-(\w+)/.exec(deco.spec?.class || '')?.[1] || 'modified';
        const at = y(doc.lineAt(from).number);
        ctx.fillStyle = changes[kind] || changes.modified;
        ctx.fillRect(0, at, 2, Math.max(2, y(doc.lineAt(to).number) - at));
      });

      // Diagnostics, straight across: a tick you can hit, at the severity's colour.
      const severity = {error: this.colour('--lee-red', '#f85149'),
                        warning: this.colour('--lee-orange', '#d29922'),
                        info: this.colour('--lee-accent', '#4493f8'),
                        hint: this.colour('--lee-fg4', '#6e7681')};
      forEachDiagnostic(this.view.state, (d, from) => {
        ctx.fillStyle = severity[d.severity] || severity.info;
        ctx.fillRect(3, Math.min(h - 2, y(doc.lineAt(from).number)), w - 5, 2);
      });

      // Where you are. Drawn last so a viewport over a dense patch still reads as the thumb.
      const top = this.view.viewportLineBlocks[0]?.from || 0;
      const bottom = this.view.viewportLineBlocks.at(-1)?.to || 0;
      const a = y(doc.lineAt(top).number), b = y(doc.lineAt(bottom).number);
      ctx.fillStyle = this.colour('--lee-fg4', '#6e7681');
      ctx.globalAlpha = .28; ctx.fillRect(0, a, w, Math.max(6, b - a)); ctx.globalAlpha = 1;
    }
    destroy() {
      removeEventListener('scroll', this.queue, true);
      this.ro?.disconnect();
      clearTimeout(this.settle);
      cancelAnimationFrame(this.frame);
      this.view.dom.classList.remove('cm-lee-has-overview');
      overviewGutter(this.scroller, false, this.gutter);
      this.dom.remove();
    }
  });
}

const stickyPlugin = ViewPlugin.fromClass(class {
  constructor(view){this.view=view;this.dom=document.createElement('div');this.dom.className='cm-lee-sticky';view.dom.appendChild(this.dom);this.draw();}
  update(update){if(update.docChanged||update.viewportChanged||update.selectionSet)this.draw();}
  draw(){const line=this.view.state.doc.lineAt(this.view.viewport.from).number;let label='';
    for(let n=line;n>=Math.max(1,line-200);n--){const t=this.view.state.doc.line(n).text.trim();if(/^(async\s+def|def|class)\s+/.test(t)){label=t;break;}}
    this.dom.textContent=label;this.dom.hidden=!label;}
  destroy(){this.dom.remove();}
});

function detectedIndentation(settings, doc='') {
  if(settings.detectIndentation===false)return settings;
  const lines=String(doc).split('\n').filter(line=>/^\s+\S/.test(line));
  if(!lines.length)return settings;
  const tabs=lines.filter(line=>line.startsWith('\t')).length;
  const widths=lines.map(line=>(line.match(/^ +/)||[''])[0].length).filter(n=>n>0);
  // Copy the file's dominant indentation kind. A tab still occupies the configured visual
  // width (four columns by default); it must never be mistaken for one space.
  if(tabs>widths.length)return {...settings,useTabs:true};
  if(widths.length<2)return {...settings,useTabs:false};
  // Hanging continuations often use 3, 5, or 7 alignment spaces. Taking the smallest
  // leading width therefore turned a normal four-space Python file into a three-column
  // editor. Score plausible indentation units by repeated levels and exact first-level
  // evidence; incidental alignment widths become outliers rather than editor policy.
  const configured=Math.max(1,Math.min(8,Number(settings.tabSize)||4));
  const candidates=[2,4,8];
  const score=unit=>{
    const divisible=widths.filter(width=>width%unit===0).length;
    const exact=widths.filter(width=>width===unit).length;
    return divisible*2+exact*3-(widths.length-divisible)*2+(unit===configured ? .25 : 0);
  };
  const unit=candidates.reduce((best,next)=>score(next)>score(best)?next:best,configured);
  return {...settings,useTabs:false,tabSize:unit};
}

function normalizedSettings(settings = {}) {
  const tabSize = Math.max(1, Math.min(8, Number(settings.tabSize) || 4));
  const lineLength = Math.max(40, Math.min(240, Number(settings.lineLength) || 100));
  const guideColumns = [lineLength, ...String(settings.guideColumns || '').split(',')
    .map(value => Math.max(20, Math.min(240, Number(value.trim()) || 0)))]
    .filter((value, index, values) => value && values.indexOf(value) === index)
    .slice(0, 4);
  return {
    tabSize, lineLength, guideColumns,
    visualGuides: settings.visualGuides !== false,
    useTabs: Boolean(settings.useTabs),
    wordWrap: settings.wordWrap === true ? 'viewport' : (settings.wordWrap || 'off'),
    wrapIndent: settings.wrapIndent || 'same',
    bracketMatching: settings.bracketMatching !== false,
    bracketColors: Boolean(settings.bracketColors),
    closeBrackets: settings.closeBrackets !== false,
    activeLine: settings.activeLine !== false,
    // `minimapMode` is what this was called while it drew a picture of the text.
    overviewMode: settings.overviewMode || settings.minimapMode || (settings.minimap ? 'always' : 'off'),
    overviewThreshold: Math.max(20, Number(settings.overviewThreshold || settings.minimapThreshold) || 120),
    stickyNavigation: settings.stickyNavigation !== false,
    lineNumbers: settings.lineNumbers || 'absolute',
    renderWhitespace: settings.renderWhitespace || 'selection',
    indentGuides: settings.indentGuides !== false,
    methodSeparators: Boolean(settings.methodSeparators),
    cursorStyle: settings.cursorStyle || 'line',
    cursorBlinking: settings.cursorBlinking || 'blink',
    scrollPastEnd: Boolean(settings.scrollPastEnd),
    smoothScrolling: settings.smoothScrolling !== false,
    folding: settings.folding !== false,
  };
}

function guideTheme(value) {
  if (!value.visualGuides || !value.guideColumns.length) return [];
  const color = v("guide", "rgba(127,127,127,.18)");
  const backgrounds = value.guideColumns.map(column =>
    `linear-gradient(to right, transparent calc(${column}ch - 1px), ${color} calc(${column}ch - 1px), ${color} ${column}ch, transparent ${column}ch)`);
  return EditorView.theme({".cm-content": {
    backgroundImage: backgrounds.join(","), backgroundRepeat: "no-repeat",
    backgroundAttachment: "local",
  }});
}

function indentColumns(text, tabSize) {
  let columns=0;
  for(const char of (text.match(/^[ \t]+/)||[''])[0])
    columns=char==='\t' ? columns+(tabSize-columns%tabSize) : columns+1;
  return columns;
}

function editorMarks(value) {
  if(value.renderWhitespace==='none'&&!value.indentGuides&&!value.methodSeparators&&!value.bracketColors)return [];
  return ViewPlugin.fromClass(class{
    constructor(view){this.decorations=this.build(view);}
    update(update){if(update.docChanged||update.viewportChanged||update.selectionSet)this.decorations=this.build(update.view);}
    build(view){const marks=[];for(const range of view.visibleRanges){let pos=range.from;
      while(pos<=range.to){const line=view.state.doc.lineAt(pos),text=line.text;
        if(value.indentGuides&&/^\s+\S/.test(text)){
          const columns=indentColumns(text,value.tabSize);
          marks.push(Decoration.line({class:'cm-lee-indent-guides',attributes:{style:`--lee-tab-size:${value.tabSize};--lee-indent-cols:${columns}`}}).range(line.from));
        }
        if(value.methodSeparators&&/^\s*(?:async\s+def|def|class)\s+/.test(text)&&line.number>1)marks.push(Decoration.line({class:'cm-lee-method-separator'}).range(line.from));
        let whitespace=[];
        if(value.renderWhitespace==='all')whitespace=[...text.matchAll(/[ \t]+/g)];
        else if(value.renderWhitespace==='trailing')whitespace=[...text.matchAll(/[ \t]+$/g)];
        else if(value.renderWhitespace==='selection'){const sel=view.state.selection.main;if(!sel.empty&&sel.to>=line.from&&sel.from<=line.to)whitespace=[...text.matchAll(/[ \t]+/g)].filter(m=>line.from+m.index<sel.to&&line.from+m.index+m[0].length>sel.from);}
        for(const match of whitespace)marks.push(Decoration.mark({class:match[0].includes('\t')?'cm-lee-tab-mark':'cm-lee-space-mark'}).range(line.from+match.index,line.from+match.index+match[0].length));
        if(value.bracketColors){let depth=0;for(let i=0;i<text.length;i++){if('([{'.includes(text[i])){depth++;marks.push(Decoration.mark({class:`cm-lee-bracket-${(depth-1)%3}`}).range(line.from+i,line.from+i+1));}else if(')]}'.includes(text[i])){marks.push(Decoration.mark({class:`cm-lee-bracket-${Math.max(0,depth-1)%3}`}).range(line.from+i,line.from+i+1));depth=Math.max(0,depth-1);}}}
        if(line.to>=range.to)break;pos=line.to+1;}}
      marks.sort((a,b)=>a.from-b.from||a.startSide-b.startSide);return Decoration.set(marks,true);}
  },{decorations:v=>v.decorations});
}

function behaviorTheme(value) {
  const cursor = value.cursorStyle === 'block'
    ? {borderLeft: '0', backgroundColor: v('accent', '#58a6ff'), width: '1ch', opacity: '.58'}
    : value.cursorStyle === 'underline'
      ? {borderLeft: '0', borderBottom: `2px solid ${v('accent', '#58a6ff')}`, width: '1ch'} : {};
  const content = {};
  if (value.scrollPastEnd) content.paddingBottom = '50vh';
  if (value.wordWrap === 'column') { content.width = `min(100%, ${value.lineLength}ch)`; content.minWidth = '0'; }
  return EditorView.theme({
    '.cm-content': content,
    '.cm-scroller': {scrollBehavior: value.smoothScrolling ? 'smooth' : 'auto'},
    '.cm-cursor, .cm-dropCursor': cursor,
    '&.cm-focused .cm-cursor': {animation: value.cursorBlinking === 'off' ? 'none' : undefined},
    '.cm-line': value.wrapIndent === 'indent' ? {paddingLeft:'2ch', textIndent:'-2ch'} :
      value.wrapIndent === 'deepIndent' ? {paddingLeft:'4ch', textIndent:'-4ch'} : {},
  });
}

function settingsExt(settings = {}, lineNums = false) {
  const value = normalizedSettings(settings), out = [
    EditorState.tabSize.of(value.tabSize),
    indentUnit.of(value.useTabs ? "\t" : " ".repeat(value.tabSize)),
    guideTheme(value), behaviorTheme(value), highlightSpecialChars(), editorMarks(value),
  ];
  if (value.wordWrap !== 'off') out.push(EditorView.lineWrapping);
  if (settings.highlightSelection !== false) out.push(highlightSelectionMatches());
  if (value.bracketMatching) out.push(bracketMatching());
  if (value.closeBrackets) out.push(closeBrackets());
  if (value.activeLine) out.push(highlightActiveLine());
  if (value.overviewMode !== 'off') out.push(overviewPlugin(value.overviewMode, value.overviewThreshold));
  if (value.stickyNavigation) out.push(stickyPlugin);
  if (lineNums && value.lineNumbers !== 'off') out.push(lineNumbers({formatNumber:(n,state)=>{
    if(value.lineNumbers==='absolute')return String(n);const current=state.doc.lineAt(state.selection.main.head).number;
    return value.lineNumbers==='hybrid'&&n===current?String(n):String(Math.abs(n-current));}}), highlightActiveLineGutter());
  if (lineNums && value.folding) out.push(foldGutter(), keymap.of(foldKeymap));
  return out;
}

export function create(el, opts = {}) {
  const {doc = "", lang = "python", readOnly = false, lineNums = false,
         placeholder = "", onChange = null, onSelection = null, onChangeClick = null, onDefinition = null,
         onBreakpoint = null, breakpoints = [], changedLines = [], binds = [], completeUrl = null,
         lintUrl = "/lint", lintPath = "", settings = {}} = opts;
  const language = new Compartment(), editable = new Compartment(), linting = new Compartment(),
        preferences = new Compartment(), initialSettings=detectedIndentation(settings,doc);

  const exts = [
    history(),
    drawSelection(),
    indentOnInput(),
    pairedTripleQuoteInput,
    pairedTripleQuotes,
    rectangularSelection(),
    crosshairCursor(),
    syntaxHighlighting(hl, {fallback: true}),
    theme,
    ghostField, inlineField, changesField, breakpointField, debugLineField, packageField, inlayHintField, ghostKeymap,
    language.of(langExt(lang)),
    editable.of(EditorView.editable.of(!readOnly)),
    linting.of(lintExt(lang, readOnly, lintUrl, lintPath)),
    preferences.of(settingsExt(initialSettings, lineNums)),
    // app bindings first, so ctrl+enter runs a cell instead of inserting a newline
    keymap.of([...appKeymap(binds), ...closeBracketsKeymap, ...searchKeymap,
               ...historyKeymap, ...completionKeymap, indentWithTab, ...defaultKeymap]),
  ];
  if (onBreakpoint) exts.unshift(breakpointGutter(onBreakpoint));
  if (onDefinition) exts.push(EditorView.domEventHandlers({mousedown(event, view) {
    const mac = /Mac|iPhone|iPad|iPod/.test(navigator.userAgentData?.platform || navigator.platform || "");
    if (!(mac ? event.metaKey : event.ctrlKey) || event.button !== 0) return false;
    const pos = view.posAtCoords({x: event.clientX, y: event.clientY});
    if (pos == null) return false;
    const line = view.state.doc.lineAt(pos), local = pos - line.from;
    const left = line.text.slice(0, local).match(/[_A-Za-z]\w*$/)?.[0] || "";
    const right = line.text.slice(local).match(/^\w*/)?.[0] || "";
    const name = left + right; if (!name) return false;
    event.preventDefault(); onDefinition(name, line.number); return true;
  }}));
  if (onChangeClick) exts.push(EditorView.domEventHandlers({click(event) {
    const line = event.target.closest?.('.cm-lee-change');
    if (!line || event.clientX > line.getBoundingClientRect().left + 12) return false;
    event.preventDefault(); onChangeClick(Number(line.dataset.changeLine) || 1); return true;
  }}));
  if (placeholder) exts.push(cmPlaceholder(placeholder));
  if (completeUrl) exts.push(autocompletion({override: [kernelCompletions(completeUrl)], activateOnTyping: initialSettings.quickSuggestions !== false}));
  else exts.push(autocompletion());
  if (onChange || onSelection) exts.push(EditorView.updateListener.of(u => {
    if (u.docChanged && onChange) onChange(u.state.doc.toString());
    if (u.selectionSet && onSelection) onSelection();
  }));

  const view = new EditorView({state: EditorState.create({doc, extensions: exts}), parent: el});
  bindFind(view);
  view._lee = {language, editable, linting, preferences, lintUrl, lintPath, readOnly, lang, lineNums};
  if (changedLines.length) setChangedLines(view, changedLines);
  if (breakpoints.length) setBreakpoints(view, breakpoints);
  return view;
}

export function createMerge(el, opts = {}) {
  const {left = '', right = '', lang = 'python', settings = {}, onChange = null,
    readOnlyRight = false, revertControls = 'a-to-b'} = opts;
  const side = (readOnly = false) => [
    settingsExt(settings), langExt(lang), syntaxHighlighting(hl, {fallback: true}), theme,
    lineNumbers(), drawSelection(), highlightSelectionMatches(), readOnly ? EditorState.readOnly.of(true) : [],
    keymap.of([...searchKeymap, ...historyKeymap, ...defaultKeymap]),
  ];
  const merge = new MergeView({parent: el, orientation: 'a-b', revertControls,
    highlightChanges: true, gutter: true,
    a: {doc: left, extensions: side(true)},
    b: {doc: right, extensions: [...side(readOnlyRight), ...(readOnlyRight ? [] : [history()]), EditorView.updateListener.of(u => {
      if (u.docChanged && onChange) onChange(u.state.doc.toString());
    })]},
  });
  bindFind(merge.a); bindFind(merge.b);
  return merge;
}
export const mergeResult = merge => merge.b.state.doc.toString();
export const destroyMerge = merge => merge.destroy();

export const getDoc = (view) => view.state.doc.toString();

export function setDoc(view, text) {
  if (getDoc(view) === text) return;               // never fight the user's cursor over an identical value
  view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: text}});
}

export function setLang(view, lang) {
  view._lee.lang = lang;
  view.dispatch({effects: [view._lee.language.reconfigure(langExt(lang)),
                           view._lee.linting.reconfigure(lintExt(lang, view._lee.readOnly, view._lee.lintUrl, view._lee.lintPath))]});
}

export function configure(view, settings = {}) {
  view.dispatch({effects: view._lee.preferences.reconfigure(settingsExt(settings, view._lee.lineNums))});
}

export function setReadOnly(view, ro) {
  view._lee.readOnly = Boolean(ro);
  view.dispatch({effects: [view._lee.editable.reconfigure(EditorView.editable.of(!ro)),
                           view._lee.linting.reconfigure(lintExt(view._lee.lang, ro, view._lee.lintUrl, view._lee.lintPath))]});
}

export function focus(view, atEnd) {
  view.focus();
  if (atEnd) view.dispatch({selection: {anchor: view.state.doc.length}});
}

export function startCompletion(view) {
  view.focus();
  return cmStartCompletion(view);
}

export const cursor = (view) => view.state.selection.main.head;
export function selection(view) {
  const range = view.state.selection.main;
  return {from: range.from, to: range.to, text: view.state.doc.sliceString(range.from, range.to)};
}
export const slice = (view, from, to) => view.state.doc.sliceString(from, to);
export function replaceRange(view, from, to, text) {
  from = Math.max(0, Math.min(Number(from) || 0, view.state.doc.length));
  to = Math.max(from, Math.min(Number(to) || from, view.state.doc.length));
  view.dispatch({changes: {from, to, insert: text}, selection: {anchor: from + text.length}});
  view.focus();
}
export function selectionCoords(view) {
  const range = view.state.selection.main;
  return range.empty ? null : (view.coordsAtPos(range.to) || view.coordsAtPos(range.from));
}
export function insert(view, text) {
  const range = view.state.selection.main;
  view.dispatch({changes: {from: range.from, to: range.to, insert: text},
                 selection: {anchor: range.from + text.length}});
}
export function setSelection(view, from, to = from) {
  from = Math.max(0, Math.min(Number(from) || 0, view.state.doc.length));
  to = Math.max(from, Math.min(Number(to) || from, view.state.doc.length));
  view.dispatch({selection: {anchor: from, head: to}, scrollIntoView: true});
  view.focus();
}
export function setCursor(view, pos) {
  const at = Math.max(0, Math.min(Number(pos) || 0, view.state.doc.length));
  view.dispatch({selection: {anchor: at}, scrollIntoView: false});
}
export const lineOf = (view) => view.state.doc.lineAt(cursor(view)).number;
export function wordAtCursor(view) {
  const pos = cursor(view), line = view.state.doc.lineAt(pos), local = pos - line.from;
  return (line.text.slice(0, local).match(/[_A-Za-z]\w*$/)?.[0] || '') +
         (line.text.slice(local).match(/^\w*/)?.[0] || '');
}
export const lineCount = (view) => view.state.doc.lines;
export const destroy = (view) => view.destroy();
export const languages = () => Object.keys(LANGS);

// False when the document has nothing left to undo, which is what lets a caller fall through to
// undoing the cell operation instead. CodeMirror owns `mod+z` while the caret is in a document.
export const undo = (view) => cmUndo(view);
export const redo = (view) => cmRedo(view);
/* `defaultKeymap` already answers Mod-] , Mod-[ and Mod-Alt-\\ inside any editor. Exporting the
   commands is what lets `core/keys.py` name them, so they reach the palette and the keys help and
   run against the cell or the file the caret is actually in. */
export const indentMore = (view) => cmIndentMore(view);
export const indentLess = (view) => cmIndentLess(view);
export const indentSelection = (view) => cmIndentSelection(view);
