// The search page's code (plan KX-04). Two parts:
// - the engine, which has no DOM, so that Node can test it (tests/js/);
// - the interface, which runs only in a browser.
// Model text is only ever shown with textContent, never as HTML.
"use strict";

// -- the engine -----------------------------------------------------------------------------------
const Engine = (() => {
  // The tokens of the retrieval evaluation (harness.words): ids such as req-1-oad-1050 stay whole.
  const WORD = /[a-z0-9]+(?:[-.][a-z0-9]+)*/g;
  const K1 = 1.2, B = 0.75, TITLE_WEIGHT = 3, MAX_PREFIX = 200;

  function tokens(text) {
    return (text || "").toLowerCase().match(WORD) || [];
  }

  // One field's BM25 index (as harness.BM25): postings per token, as typed arrays once finished.
  class Field {
    constructor() {
      this.building = new Map(); // token -> [doc, count, doc, count, ...]
      this.lengths = [];
      this.total = 0;
    }
    add(doc, text) {
      const toks = tokens(text);
      const counts = new Map();
      for (const t of toks) counts.set(t, (counts.get(t) || 0) + 1);
      for (const [t, c] of counts) {
        let p = this.building.get(t);
        if (!p) this.building.set(t, (p = []));
        p.push(doc, c);
      }
      this.lengths[doc] = toks.length;
      this.total += toks.length;
    }
    finish(n) {
      this.n = n;
      this.len = new Float32Array(n);
      for (let d = 0; d < n; d++) this.len[d] = this.lengths[d] || 0;
      this.avg = n ? this.total / n : 1;
      this.post = new Map();
      for (const [t, p] of this.building) {
        const docs = new Int32Array(p.length / 2), tf = new Float32Array(p.length / 2);
        for (let i = 0, j = 0; i < p.length; i += 2, j++) {
          docs[j] = p[i];
          tf[j] = p[i + 1];
        }
        this.post.set(t, { docs, tf });
      }
      this.building = null;
      this.lengths = null;
      this.vocab = [...this.post.keys()].sort();
    }
    // Adds weight × BM25(token) to `into` for every document holding the token; marks `hit`.
    score(token, weight, into, hit) {
      const p = this.post.get(token);
      if (!p) return;
      const df = p.docs.length;
      const idf = Math.log(1 + (this.n - df + 0.5) / (df + 0.5));
      for (let i = 0; i < df; i++) {
        const d = p.docs[i], tf = p.tf[i];
        const norm = K1 * (1 - B + (B * this.len[d]) / this.avg);
        into[d] += (weight * idf * tf * (K1 + 1)) / (tf + norm);
        hit[d] = 1;
      }
    }
    // The tokens that start with `prefix`, at most MAX_PREFIX.
    expand(prefix) {
      const v = this.vocab, out = [];
      let lo = 0, hi = v.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (v[mid] < prefix) lo = mid + 1;
        else hi = mid;
      }
      for (let i = lo; i < v.length && v[i].startsWith(prefix) && out.length < MAX_PREFIX; i++) out.push(v[i]);
      return out;
    }
  }

  // A query: words, "quoted phrases" and prefix* terms. Each becomes a group of tokens; an
  // item matches a group when it holds any of its tokens.
  function parse(query) {
    const phrases = [];
    const rest = (query || "").replace(/"([^"]*)"/g, (_, p) => {
      if (p.trim()) phrases.push(p.trim().toLowerCase().replace(/\s+/g, " "));
      return " ";
    });
    const groups = [];
    for (const part of rest.split(/\s+/).filter(Boolean)) {
      const prefix = part.endsWith("*");
      const toks = tokens(prefix ? part.slice(0, -1) : part);
      toks.forEach((t, i) => groups.push({ token: t, prefix: prefix && i === toks.length - 1 }));
    }
    for (const p of phrases) for (const t of tokens(p)) groups.push({ token: t, prefix: false });
    return { groups, phrases };
  }

  class Index {
    constructor() {
      this.items = [];
      this.title = new Field();
      this.body = new Field();
    }
    add(item) {
      const d = this.items.length;
      this.items.push(item);
      this.title.add(d, [item.id, item.n].filter(Boolean).join(" "));
      this.body.add(d, [item.w, item.x, item.c, item.of && item.of[1]].filter(Boolean).join("\n"));
      return d;
    }
    finish() {
      const n = this.items.length;
      this.title.finish(n);
      this.body.finish(n);
    }
    // Ranked items: those holding every group first, then by score. Filters: `project` (an
    // item's p) and `type` (its t). Returns {total, all, hits: [{doc, score, matched}], terms}.
    search(query, { project = null, type = null, limit = 200 } = {}) {
      const { groups, phrases } = parse(query);
      const n = this.items.length;
      const score = new Float64Array(n), matched = new Uint16Array(n), terms = [];
      for (const g of groups) {
        const toks = g.prefix ? this.title.expand(g.token).concat(this.body.expand(g.token)) : [g.token];
        const hit = new Uint8Array(n);
        for (const t of new Set(toks)) {
          this.title.score(t, TITLE_WEIGHT, score, hit);
          this.body.score(t, 1, score, hit);
          terms.push(t);
        }
        for (let d = 0; d < n; d++) matched[d] += hit[d];
      }
      const hits = [];
      for (let d = 0; d < n; d++) {
        if (!matched[d]) continue;
        const it = this.items[d];
        if (project !== null && it.p !== project) continue;
        if (type !== null && it.t !== type) continue;
        if (phrases.length) {
          const hay = [it.n, it.w, it.x, it.c].filter(Boolean).join("\n").toLowerCase().replace(/\s+/g, " ");
          if (!phrases.every((p) => hay.includes(p))) continue;
        }
        hits.push({ doc: d, score: score[d], matched: matched[d] });
      }
      hits.sort((a, b) => b.matched - a.matched || b.score - a.score || a.doc - b.doc);
      const all = hits.filter((h) => h.matched === groups.length).length;
      return { total: hits.length, all, hits: hits.slice(0, limit), terms, groups: groups.length };
    }
  }

  // A short excerpt of `text` around the first query term, as [{text, mark}] pieces.
  function snippet(text, terms, width = 90) {
    text = (text || "").replace(/\s+/g, " ").trim();
    if (!text) return [];
    const lower = text.toLowerCase();
    let at = -1;
    for (const t of terms) {
      const i = lower.indexOf(t);
      if (i >= 0 && (at < 0 || i < at)) at = i;
    }
    const start = Math.max(0, at < 0 ? 0 : at - width);
    const end = Math.min(text.length, (at < 0 ? 0 : at) + 2 * width);
    const piece = (start > 0 ? "…" : "") + text.slice(start, end) + (end < text.length ? "…" : "");
    return mark(piece, terms);
  }

  function mark(text, terms) {
    const lower = text.toLowerCase(), out = [];
    let i = 0;
    while (i < text.length) {
      let best = -1, len = 0;
      for (const t of terms) {
        const j = lower.indexOf(t, i);
        if (j >= 0 && (best < 0 || j < best || (j === best && t.length > len))) {
          best = j;
          len = t.length;
        }
      }
      if (best < 0) {
        out.push({ text: text.slice(i), mark: false });
        break;
      }
      if (best > i) out.push({ text: text.slice(i, best), mark: false });
      out.push({ text: text.slice(best, best + len), mark: true });
      i = best + len;
    }
    return out;
  }

  // A block's base64 of gzipped text back into its text, and a data block into its object.
  async function decodeText(base64) {
    const bin = atob(base64.trim());
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).text();
  }

  async function decode(base64) {
    return JSON.parse(await decodeText(base64));
  }

  return { tokens, parse, Field, Index, snippet, mark, decode, decodeText };
})();

if (typeof module !== "undefined") module.exports = Engine;

// -- the interface --------------------------------------------------------------------------------
if (typeof document !== "undefined") {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  };
  const now = () => performance.now();
  const secs = (ms) => (ms / 1000).toFixed(1) + " s";
  const fmt = (n) => n.toLocaleString("en-US");
  const count = (n, noun) => `${fmt(n)} ${noun}${n === 1 ? "" : "s"}`;
  const pause = () => new Promise((r) => setTimeout(r, 0));
  const SLICE_MS = 30, STALL_MS = 10000;

  const state = { index: new Engine.Index(), projects: [], byKey: new Map(), summaries: new Map(), cancelled: false };

  // While the file is still being read: a small script after each data block calls this.
  window.__read = (i, n) => {
    const r = $("reading");
    if (r) r.textContent = `Reading the file: model ${i} of ${n}…`;
  };

  function problem(text) {
    const p = $("problem");
    p.textContent = text;
    p.hidden = false;
  }

  function checks() {
    const path = decodeURIComponent(location.pathname).replace(/\\/g, "/");
    if (/\/AppData\/Local\/Temp\/.*(Temp\d*_|\.zip)/i.test(path)) {
      problem("This page was opened from inside a zip file, from a temporary folder. Save it, or use " +
              "Extract All on the zip, and open it from there.");
    }
    if (typeof DecompressionStream === "undefined") {
      problem("This browser can't unpack the page's data. Open it in a current Edge, Chrome, Firefox or Safari.");
      return false;
    }
    return true;
  }

  // The loading panel: a bar per phase, with its time; a note when a phase stalls.
  function phases(names) {
    const box = $("phases"), rows = {};
    for (const [key, label] of names) {
      const row = el("div", "phase");
      const name = el("span", "phase-name", label), bar = el("progress"), info = el("span", "phase-info", "waiting");
      bar.max = 1;
      bar.value = 0;
      row.append(name, bar, info);
      box.append(row);
      rows[key] = { bar, info, ms: 0, done: 0, total: 0, last: now() };
    }
    let lastMove = now();
    const timer = setInterval(() => {
      const stalled = now() - lastMove > STALL_MS;
      $("stall").hidden = !stalled;
    }, 1000);
    return {
      rows,
      update(key, done, total, detail) {
        const r = rows[key];
        r.done = done;
        r.total = total;
        r.bar.max = Math.max(1, total);
        r.bar.value = done;
        r.info.textContent = `${detail ? detail + ", " : ""}${secs(r.ms)}`;
        lastMove = now();
      },
      time(key, ms) {
        rows[key].ms += ms;
      },
      stop() {
        clearInterval(timer);
        $("stall").hidden = true;
      },
    };
  }

  async function load() {
    $("reading").textContent = "Read the file.";
    const blocks = [...document.querySelectorAll('script[type="application/octet-stream"][data-project]')];
    const totalItems = blocks.reduce((s, b) => s + Number(b.dataset.items || 0), 0);
    const P = phases([["unpack", "Unpacking"], ["index", "Indexing items"], ["finish", "Finishing the index"]]);
    const started = now();
    let items = 0;
    for (let i = 0; i < blocks.length; i++) {
      if (state.cancelled) return;
      const b = blocks[i], name = b.dataset.project;
      P.update("unpack", i, blocks.length, `${name} (${i + 1} of ${blocks.length})`);
      await pause();
      const t = now();
      const data = await Engine.decode(b.textContent);
      P.time("unpack", now() - t);
      b.textContent = ""; // the block's text is no longer needed
      const pid = state.projects.length;
      state.projects.push(data.project);
      P.update("unpack", i + 1, blocks.length, name);
      let sliceStart = now();
      for (const item of data.items) {
        item.p = pid;
        const d = state.index.add(item);
        const key = pid + "\u0000" + item.k;
        if (item.t === "summary") {
          if (!state.summaries.has(key)) state.summaries.set(key, []);
          state.summaries.get(key).push(d);
        } else {
          state.byKey.set(key, d);
        }
        items++;
        if (now() - sliceStart > SLICE_MS) {
          P.time("index", now() - sliceStart);
          P.update("index", items, totalItems, `${fmt(items)} of ${fmt(totalItems)}`);
          await pause();
          if (state.cancelled) return;
          sliceStart = now();
        }
      }
      P.time("index", now() - sliceStart);
      P.update("index", items, totalItems, `${fmt(items)} of ${fmt(totalItems)}`);
    }
    P.update("finish", 0, 1, "compacting");
    await pause();
    const t = now();
    state.index.finish();
    P.time("finish", now() - t);
    P.update("finish", 1, 1, "done");
    P.stop();
    const r = P.rows;
    $("ready").textContent =
      `${count(items, "item")} from ${count(state.projects.length, "model")}, ready in ${secs(now() - started)} ` +
      `(unpacking ${secs(r.unpack.ms)}, indexing ${secs(r.index.ms)}, finishing ${secs(r.finish.ms)}).`;
    show();
  }

  function show() {
    $("loading").hidden = true;
    $("app").hidden = false;
    const sel = $("project");
    state.projects.forEach((p, i) => sel.append(new Option(p.label, String(i))));
    const types = [...new Set(state.index.items.map((it) => it.t))].sort();
    for (const t of types) $("type").append(new Option(t[0].toUpperCase() + t.slice(1), t));
    let timer = null;
    const go = () => {
      clearTimeout(timer);
      timer = setTimeout(run, 150);
    };
    $("q").addEventListener("input", go);
    $("project").addEventListener("change", run);
    $("type").addEventListener("change", run);
    window.addEventListener("hashchange", detail);
    $("q").focus();
    const q = /^#q=(.*)$/.exec(location.hash); // a link can carry a search: page.html#q=REQ-1
    if (q) {
      $("q").value = decodeURIComponent(q[1]);
      run();
    }
    detail();
  }

  let last = { terms: [] };

  function run() {
    const q = $("q").value;
    const list = $("results"), info = $("count");
    list.replaceChildren();
    if (!q.trim()) {
      info.textContent = "";
      return;
    }
    const t = now();
    const project = $("project").value === "" ? null : Number($("project").value);
    const type = $("type").value || null;
    const res = state.index.search(q, { project, type });
    last = res;
    const ms = now() - t;
    info.textContent = res.total
      ? `${fmt(res.total)} found (${fmt(res.all)} with every word) in ${(ms / 1000).toFixed(2)} s` +
        (res.total > res.hits.length ? `; the first ${res.hits.length} shown` : "")
      : `Nothing found (${(ms / 1000).toFixed(2)} s)`;
    for (const h of res.hits) list.append(resultRow(h, res.terms));
  }

  function badge(it) {
    if (it.t === "summary") return `${it.kd || "Summary"} (generated)`;
    return it.kd || it.t;
  }

  function resultRow(h, terms) {
    const it = state.index.items[h.doc];
    const row = el("a", "result");
    row.href = "#d" + h.doc;
    const head = el("div", "result-head");
    head.append(el("span", "badge", badge(it)), el("span", "result-name", it.n || it.k));
    if (it.id && !(it.n || "").includes(it.id)) head.append(el("span", "result-id", it.id));
    row.append(head, el("div", "result-where", `${state.projects[it.p].label}${it.w ? " · " + it.w : ""}`));
    const snip = el("div", "result-snippet");
    for (const piece of Engine.snippet(it.x || it.c || "", terms)) snip.append(piece.mark ? el("mark", null, piece.text) : piece.text);
    row.append(snip);
    return row;
  }

  function link(pid, key, label) {
    const d = state.byKey.get(pid + "\u0000" + key);
    if (d === undefined) return el("span", null, label);
    const a = el("a", null, label);
    a.href = "#d" + d;
    return a;
  }

  function section(title, body) {
    const s = el("section", "detail-section");
    s.append(el("h3", null, title), body);
    return s;
  }

  function textBlock(text) {
    const pre = el("pre", "text");
    for (const piece of Engine.mark(text, last.terms || [])) pre.append(piece.mark ? el("mark", null, piece.text) : piece.text);
    return pre;
  }

  function detail() {
    const pane = $("detail");
    const m = /^#d(\d+)$/.exec(location.hash);
    if (!m) {
      pane.replaceChildren(el("p", "hint", "Search above; choose a result to read it here."));
      return;
    }
    const it = state.index.items[Number(m[1])];
    const pid = it ? it.p : -1, project = state.projects[pid];
    if (!it || !project) {
      pane.replaceChildren(el("p", "hint", "That item isn't in this page."));
      return;
    }
    const out = [el("h2", null, it.n || it.k), el("div", "badges")];
    out[1].append(el("span", "badge", badge(it)));
    const facts = el("table", "facts");
    const fact = (k, v) => {
      if (v === undefined || v === null || v === "") return;
      const tr = el("tr");
      const td = el("td");
      td.append(v instanceof Node ? v : document.createTextNode(String(v)));
      tr.append(el("th", null, k), td);
      facts.append(tr);
    };
    fact("Id", it.id);
    fact("Database number", it.db);
    if (it.t === "summary" && it.of) fact("Of", link(pid, it.of[0], it.of[1]));
    fact("Where", it.w);
    fact("Model", project.label);
    fact("Source", (project.sources || []).map((s) => s.path).join("; "));
    const meta = (project.sources || []).flatMap((s) => Object.entries(s.metadata || {}).map(([k, v]) => `${k}=${v}`));
    fact("Metadata", [...new Set(meta)].join("; "));
    if (it.m) fact("Generated by", `${it.m}; not part of the source model`);
    if (it.l) fact("Listed in", link(pid, it.l[0], it.l[1]));
    out.push(facts);
    if (it.x) out.push(section(it.t === "requirement" ? "Requirement text" : it.t === "summary" ? "Summary" : "Text", textBlock(it.x)));
    if (it.r && it.r.length) {
      const groups = new Map();
      for (const [, , phrase, okey, olabel] of it.r) {
        if (!groups.has(phrase)) groups.set(phrase, []);
        groups.get(phrase).push(link(pid, okey, olabel));
      }
      const ul = el("ul", "relations");
      for (const [phrase, links] of groups) {
        const li = el("li");
        li.append(el("span", "phrase", phrase + " "));
        links.forEach((a, i) => li.append(...(i ? [", ", a] : [a])));
        ul.append(li);
      }
      out.push(section("Relationships", ul));
    }
    if (it.d && it.d.length) {
      const p = el("p");
      it.d.forEach(([k, label], i) => p.append(...(i ? [", ", link(pid, k, label)] : [link(pid, k, label)])));
      out.push(section("Shown in diagrams", p));
    }
    const sums = it.t === "summary" ? [] : (state.summaries.get(pid + "\u0000" + it.k) || []).map((d) => state.index.items[d]);
    for (const s of sums) {
      const body = el("div");
      body.append(el("p", "generated", `Generated by ${s.m}; not part of the source model.`), textBlock(s.x));
      out.push(section(s.kd || "Summary", body));
    }
    if (it.sk && it.sk.length) out.push(section("Sketch", sketchBox(it)));
    if (it.c) out.push(section("As the RAG reads it", textBlock(it.c)));
    pane.replaceChildren(...out);
    pane.scrollTop = 0;
  }

  // A diagram's sketches, decoded when it is opened: WebP images, or an SVG whose shapes open
  // their elements. SVG is parsed as SVG, never as HTML.
  let sketchBlocks = null;
  function sketchBox(it) {
    if (!sketchBlocks) {
      sketchBlocks = new Map();
      for (const b of document.querySelectorAll("script[data-sketch]")) sketchBlocks.set(b.dataset.sketch, b);
    }
    const box = el("div", "sketches");
    const note = el("p", "hint", "Drawn from the model's layout, not a Cameo rendering. Click to zoom.");
    box.append(note);
    it.sk.forEach((id, i) => {
      const b = sketchBlocks.get(id);
      if (!b) return;
      const frame = el("div", "sketch");
      frame.addEventListener("click", (e) => {
        if (!e.target.closest || !e.target.closest("[data-k]")) frame.classList.toggle("zoomed");
      });
      if (i > 0) box.append(el("p", "hint", `Module M${i}`));
      box.append(frame);
      if (b.dataset.format === "webp") {
        const img = el("img");
        img.alt = `Sketch of ${it.n}`;
        img.src = "data:image/webp;base64," + b.textContent.trim();
        frame.append(img);
        return;
      }
      frame.append(el("p", "hint", "Unpacking the sketch…"));
      Engine.decodeText(b.textContent).then((text) => {
        const doc = new DOMParser().parseFromString(text, "image/svg+xml");
        const svg = doc.documentElement;
        if (svg.nodeName !== "svg") {
          frame.replaceChildren(el("p", "hint", "This sketch could not be read."));
          return;
        }
        for (const g of svg.querySelectorAll("[data-k]")) {
          const d = state.byKey.get(it.p + "\u0000" + g.getAttribute("data-k"));
          if (d === undefined) continue;
          g.classList.add("linked");
          g.addEventListener("click", () => { location.hash = "#d" + d; });
        }
        frame.replaceChildren(document.importNode(svg, true));
      });
    });
    return box;
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("cancel").addEventListener("click", () => {
      state.cancelled = true;
      problem("Stopped. Reload the page to load it again.");
    });
    if (checks()) {
      load().catch((e) => problem(`Loading failed: ${e && e.message ? e.message : e}. Try another browser.`));
    }
  });
}
