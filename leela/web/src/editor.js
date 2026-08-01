// CodeMirror 6 wrapper for the leela IDE.
//
// Bundled to ../static/lee-cm6.js and committed, so the IDE works offline and a
// user installing from PyPI never needs node. Rebuild with `npm run build`.
//
// The page talks to this through one small surface (`window.LeeCM`) rather than
// importing CodeMirror itself, so the keymap that Python owns stays the single
// source of truth: `create()` takes the bindings it should honour, and anything
// it does not recognise is left to bubble up to the document handler.

import {EditorState, Compartment, StateEffect, StateField, Prec} from "@codemirror/state";
import {EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter,
        drawSelection, rectangularSelection, crosshairCursor, Decoration, WidgetType,
        placeholder as cmPlaceholder} from "@codemirror/view";
import {defaultKeymap, history, historyKeymap, indentWithTab} from "@codemirror/commands";
import {searchKeymap, highlightSelectionMatches} from "@codemirror/search";
import {autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap,
        startCompletion as cmStartCompletion} from "@codemirror/autocomplete";
import {syntaxHighlighting, HighlightStyle, indentUnit, bracketMatching,
        foldGutter, foldKeymap, indentOnInput} from "@codemirror/language";
import {tags as t} from "@lezer/highlight";

import {python} from "@codemirror/lang-python";
import {markdown} from "@codemirror/lang-markdown";
import {javascript} from "@codemirror/lang-javascript";
import {json} from "@codemirror/lang-json";
import {html} from "@codemirror/lang-html";
import {css} from "@codemirror/lang-css";
import {sql} from "@codemirror/lang-sql";
import {yaml} from "@codemirror/lang-yaml";

// Language ids match leela.fs.LANGS, so Python decides the mode and both
// frontends resolve the same name.
const LANGS = {
  python, markdown, javascript, json, html, css, sql, yaml,
  typescript: () => javascript({typescript: true}),
  jsx: () => javascript({jsx: true}),
  tsx: () => javascript({jsx: true, typescript: true}),
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
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection":
    {backgroundColor: v("sel", "#264f78")},
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

function langExt(name) {
  const f = LANGS[name];
  return f ? f() : [];
}

// A completion source backed by the kernel: the same /complete contract the TUI
// uses, so completions come from the real namespace (venv modules included)
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

// Turn the Python-side chord table into CodeMirror bindings. Anything the app
// did not ask for is not bound here at all, so it reaches the document handler.
function appKeymap(binds) {
  return (binds || []).map(b => ({
    key: b.cm,
    preventDefault: true,
    run: () => { b.run(); return true; },
  }));
}

export function create(el, opts = {}) {
  const {doc = "", lang = "python", readOnly = false, lineNums = false,
         placeholder = "", onChange = null, binds = [], completeUrl = null} = opts;
  const language = new Compartment(), editable = new Compartment();

  const exts = [
    history(),
    drawSelection(),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    highlightActiveLine(),
    highlightSelectionMatches(),
    rectangularSelection(),
    crosshairCursor(),
    indentUnit.of("    "),
    syntaxHighlighting(hl, {fallback: true}),
    theme,
    ghostField, ghostKeymap,
    language.of(langExt(lang)),
    editable.of(EditorView.editable.of(!readOnly)),
    // app bindings first, so ctrl+enter runs a cell instead of inserting a newline
    keymap.of([...appKeymap(binds), ...closeBracketsKeymap, ...searchKeymap,
               ...historyKeymap, ...completionKeymap, indentWithTab, ...defaultKeymap]),
  ];
  if (lineNums) exts.push(lineNumbers(), highlightActiveLineGutter(), foldGutter(), keymap.of(foldKeymap));
  if (placeholder) exts.push(cmPlaceholder(placeholder));
  if (completeUrl) exts.push(autocompletion({override: [kernelCompletions(completeUrl)], activateOnTyping: true}));
  else exts.push(autocompletion());
  if (onChange) exts.push(EditorView.updateListener.of(u => { if (u.docChanged) onChange(u.state.doc.toString()); }));

  const view = new EditorView({state: EditorState.create({doc, extensions: exts}), parent: el});
  view._lee = {language, editable};
  return view;
}

export const getDoc = (view) => view.state.doc.toString();

export function setDoc(view, text) {
  if (getDoc(view) === text) return;               // never fight the user's cursor over an identical value
  view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: text}});
}

export function setLang(view, lang) {
  view.dispatch({effects: view._lee.language.reconfigure(langExt(lang))});
}

export function setReadOnly(view, ro) {
  view.dispatch({effects: view._lee.editable.reconfigure(EditorView.editable.of(!ro))});
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
export const lineOf = (view) => view.state.doc.lineAt(cursor(view)).number;
export const lineCount = (view) => view.state.doc.lines;
export const destroy = (view) => view.destroy();
export const languages = () => Object.keys(LANGS);
