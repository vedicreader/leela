// html-manager fed by Leela's `/nb/comm/ws` socket in place of a Jupyter kernel connection. Only the
// core modules load: nothing is fetched from a CDN, and `requirejs` is never consulted.
import {HTMLManager} from '@jupyter-widgets/html-manager/lib/htmlmanager';
import * as base from '@jupyter-widgets/base';
import * as controls from '@jupyter-widgets/controls';
import * as output from '@jupyter-widgets/html-manager/lib/output';
import shadowCSS from './widgets.built.txt';

const CORE = {'@jupyter-widgets/base': base, '@jupyter-widgets/controls': controls, '@jupyter-widgets/output': output};
//: ipywidgets 8 speaks protocol 2.1; 7 speaks 2.0.
const PROTOCOL = /^2\.1(\.|$)/;
//: No kernel status reaches the page, so a send counts as answered at its echo or after this long.
const IDLE_MS = 500, KEPT = 500;

//: For a shadow root: `:root` matches nothing there, and fonts are registered on the document instead.
export const css = shadowCSS.replace(/@font-face\s*\{[^}]*\}/g, '').replace(/:root\b/g, ':host');
export const isCore = mod => !!CORE[mod];

const toB64 = b => {
  const u = b instanceof ArrayBuffer ? new Uint8Array(b) : new Uint8Array(b.buffer, b.byteOffset, b.byteLength);
  let s = ''; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000));
  return btoa(s);
};
const fromB64 = s => { const t = atob(s), u = new Uint8Array(t.length); for (let i = 0; i < t.length; i++) u[i] = t.charCodeAt(i); return new DataView(u.buffer); };

class Comm {
  constructor(mgr, comm_id, target_name) { Object.assign(this, {mgr, comm_id, target_name, dead: false}); }
  open(data, callbacks, metadata, buffers) { return this.mgr._send(this, 'comm_open', data, callbacks, metadata, buffers); }
  send(data, callbacks, metadata, buffers) { return this.dead ? '' : this.mgr._send(this, 'comm_msg', data, callbacks, metadata, buffers); }
  close(data, callbacks, metadata, buffers) {
    if (this.dead) return '';
    this.dead = true; this.mgr.comms.delete(this.comm_id);
    return this.mgr._send(this, 'comm_close', data, callbacks, metadata, buffers);
  }
  on_msg(fn) { this.onMsg = fn; }
  on_close(fn) { this.onClose = fn; }
}

export class Manager extends HTMLManager {
  constructor({post, info, output, refused, registered}) {
    super();
    Object.assign(this, {post, info, onOutput: output, onRefused: refused, onRegistered: registered});
    this.comms = new Map(); this.sent = new Map(); this.refusals = new Map(); this.early = new Map();
  }
  loadClass(className, moduleName, moduleVersion) {
    const cls = CORE[moduleName]?.[className];
    return cls ? Promise.resolve(cls) : Promise.reject(new Error(`${className} from ${moduleName}@${moduleVersion} is not a core widget`));
  }
  callbacks(view) { return {iopub: {output: m => this.onOutput(view, m)}}; }
  comm(id, target) {
    let c = this.comms.get(id);
    if (!c) this.comms.set(id, c = new Comm(this, id, target));
    return c;
  }
  async _create_comm(target_name, model_id, data, metadata, buffers) {
    const c = this.comm(model_id || base.uuid(), target_name);
    if (data || metadata) c.open(data || {}, {}, metadata, buffers);
    return c;
  }
  async _get_comm_info() { return (await this.info(this.comm_target_name)).comms || {}; }
  refusal(id) { return this.refusals.get(id); }
  refuse(id, why) { this.refusals.set(id, why); this.onRefused(id, why); }
  register_model(model_id, promise) {
    super.register_model(model_id, promise);
    const early = this.early.get(model_id);
    if (early) { this.early.delete(model_id); promise.then(() => early.forEach(m => this._captured(m))); }
    promise.then(() => this.onRegistered?.(model_id), () => {});
  }
  async new_model(options, state = {}) {
    if (!CORE[options.model_module]) return this.refuse(options.model_id || options.comm?.comm_id, {module: options.model_module});
    return super.new_model(options, state);
  }
  _send(comm, msg_type, data, callbacks, metadata, buffers) {
    const id = base.uuid();
    this.post({op: 'send', id, comm_id: comm.comm_id, msg_type, data: data || {}, metadata: metadata || {},
               target_name: msg_type === 'comm_open' ? comm.target_name : null, buffers: (buffers || []).map(toB64)});
    if (callbacks?.iopub) {
      this.sent.set(id, {iopub: callbacks.iopub, timer: setTimeout(() => this._idle(id), IDLE_MS)});
      if (this.sent.size > KEPT) this.sent.delete(this.sent.keys().next().value);
    }
    return id;
  }
  _idle(id) {
    const s = this.sent.get(id); if (!s || s.idled) return;
    s.idled = true; clearTimeout(s.timer);
    s.iopub.status?.({header: {msg_type: 'status'}, parent_header: {msg_id: id}, content: {execution_state: 'idle'}});
  }
  receive(m) {
    m.buffers = (m.buffers || []).map(fromB64);
    const c = m.content || {}, parent = m.parent_header?.msg_id, s = parent && this.sent.get(parent);
    if (m.msg_type === 'comm_open') return this._opened(m);
    if (m.msg_type === 'comm_msg' || m.msg_type === 'comm_close') {
      const comm = this.comms.get(c.comm_id);
      if (comm && m.msg_type === 'comm_msg') comm.onMsg?.(m);
      else if (comm) { comm.dead = true; this.comms.delete(c.comm_id); comm.onClose?.(m); }
      if (s) this._idle(parent);
      return;
    }
    if (m.output_comm_id) return this._captured(m);
    return s ? s.iopub.output?.(m) : this.onOutput(null, m);
  }
  _opened(m) {
    const c = m.content, st = c.data?.state || {}, ver = m.metadata?.version || '';
    // A subscriber can be handed a `comm_open` queued before it joined, for a model it already has.
    if (c.target_name !== this.comm_target_name || this.has_model(c.comm_id)) return;
    if (!PROTOCOL.test(ver)) return this.refuse(c.comm_id, {protocol: ver});
    const far = [st._model_module, st._view_module].find(mod => mod && !CORE[mod]);
    if (far) return this.refuse(c.comm_id, {module: far});
    return this.handle_comm_open(this.comm(c.comm_id, c.target_name), m);
  }
  async _captured(m) {
    // Output a widget captured before the page met the widget, as when the page loads its state from the kernel.
    if (!this.has_model(m.output_comm_id)) {
      const q = this.early.get(m.output_comm_id) || [];
      if (q.length < KEPT) q.push(m);
      this.early.set(m.output_comm_id, q);
      if (this.early.size > KEPT) this.early.delete(this.early.keys().next().value);
      return;
    }
    const model = await this.get_model(m.output_comm_id);
    if (!model?.outputs) return;
    const t = m.msg_type, c = m.content;
    if (t === 'clear_output') model.clear_output(c.wait);
    else if (t === 'stream') model.outputs.add({output_type: 'stream', name: c.name, text: c.text});
    else if (t === 'error') model.outputs.add({output_type: 'error', ename: c.ename, evalue: c.evalue, traceback: c.traceback});
    else if (t === 'execute_result') model.outputs.add({output_type: t, data: c.data, metadata: c.metadata || {}, execution_count: c.execution_count});
    else model.outputs.add({output_type: 'display_data', data: c.data, metadata: c.metadata || {}});
    // Kept on the kernel's model too, so a page that reconnects draws what was captured.
    model.set('outputs', model.outputs.toJSON(), {newMessage: true});
    model.save_changes();
  }
  async forget(live) {
    for (const id of Object.keys(this._models)) {
      if (id in live) continue;
      const c = this.comms.get(id); if (c) c.dead = true;
      this.comms.delete(id);
      (await this._models[id])?.close(true);
    }
  }
  kill() {
    for (const c of this.comms.values()) c.dead = true;
    for (const s of this.sent.values()) clearTimeout(s.timer);
    this.comms.clear(); this.sent.clear();
    return this.clear_state();
  }
}
