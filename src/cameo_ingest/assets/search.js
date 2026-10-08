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
      // The chunks' text holds the item's own text, so that isn't indexed twice.
      this.body.add(d, [item.w, item.c || item.x, item.of && item.of[1]].filter(Boolean).join("\n"));
      return d;
    }
    finish() {
      const n = this.items.length;
      this.title.finish(n);
      this.body.finish(n);
    }
    // Ranked items: those holding every group first, then by score. Filters: `project` (an
    // item's p), `projects` (a Set of them) and `type` (its t). Returns {total, all, hits:
    // [{doc, score, matched}], terms}.
    search(query, { project = null, projects = null, type = null, limit = 200 } = {}) {
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
        if (projects !== null && !projects.has(it.p)) continue;
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
  // The browser decodes a data: URL's base64 natively, much faster than atob and a loop; atob
  // remains for a browser that won't fetch one.
  async function bytesOf(base64) {
    try {
      return (await fetch("data:application/octet-stream;base64," + base64.trim())).body;
    } catch (e) {
      const bin = atob(base64.trim());
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      return new Blob([bytes]).stream();
    }
  }

  async function decodeText(base64) {
    const stream = (await bytesOf(base64)).pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).text();
  }

  async function decode(base64) {
    return JSON.parse(await decodeText(base64));
  }

  // Subjects (plan SB, ADR-0031): which subject of a family's view an item is in, and search results
  // grouped by subject, groups in the order of their best result, an item held by several versions
  // of a model once.
  // Topics across models (plan SB CP4) gather the families' subjects, in their default views: an
  // item's topic is its subject's.
  const UNSORTED = -1;
  class Subjects {
    constructor(families, topics) {
      this.families = families || [];
      this.topics = topics && topics.v && topics.v.length ? topics : null;
      this.topicOf = new Map(); // topic view id -> Map("family/subject" -> topic)
      for (const v of this.topics ? this.topics.v : []) {
        const m = new Map();
        v.s.forEach((t, ti) => { for (const [fi, si] of t.m) m.set(fi + "/" + si, ti); });
        for (const [fi, si] of v.u || []) m.set(fi + "/" + si, UNSORTED);
        this.topicOf.set(v.id, m);
      }
      this.familyOf = new Map(); // page id of a project -> its family
      this.where = this.families.map(() => new Map()); // per family: view id -> Map(diagram key -> subject)
      this.families.forEach((f, fi) => {
        for (const pid of f.p) this.familyOf.set(pid, fi);
        for (const v of f.v) {
          const m = new Map();
          v.s.forEach((s, si) => { for (const k of s.d) m.set(k, si); });
          for (const k of v.u || []) m.set(k, UNSORTED);
          this.where[fi].set(v.id, m);
        }
      });
    }

    view(fi, vid) {
      const f = this.families[fi];
      return f.v.find((v) => v.id === vid) || f.v.find((v) => v.id === f.dv) || f.v[0];
    }

    // The subject an item is in: a diagram's own; any other item's, where most of the diagrams that
    // show it are (the first such subject on a tie). null: shown in no diagram the view sorts.
    place(it, fi, vid) {
      const m = this.where[fi].get(this.view(fi, vid).id);
      if (it.t === "diagram") return m.has(it.k) ? m.get(it.k) : null;
      const votes = new Map();
      for (const [k] of it.d || []) if (m.has(k)) votes.set(m.get(k), (votes.get(m.get(k)) || 0) + 1);
      let best = null, most = 0;
      for (const [s, n] of votes) if (n > most || (n === most && s < best)) { best = s; most = n; }
      return best;
    }

    label(fi, vid, s) {
      if (s === null) return "Not on a sorted diagram";
      if (s === UNSORTED) return "Not sorted yet";
      return this.view(fi, vid).s[s].l;
    }

    topicView(tid) {
      if (!this.topics) return null;
      return this.topics.v.find((v) => v.id === tid) || this.topics.v.find((v) => v.id === this.topics.dv) || this.topics.v[0];
    }

    // The topic an item is in: that of its subject in its family's default view. null: on no sorted
    // diagram; UNSORTED: its subject, or its subject's topic, not sorted yet.
    topic(it, fi, tid) {
      return this.topicOfSubject(fi, this.place(it, fi, this.families[fi].dv), tid);
    }

    // The topic of subject `s` of family `fi`'s default view (null and UNSORTED as for `topic`).
    topicOfSubject(fi, s, tid) {
      if (s === null || s === UNSORTED) return s;
      const t = this.topicOf.get(this.topicView(tid).id).get(fi + "/" + s);
      return t === undefined ? UNSORTED : t;
    }

    topicLabel(tid, t) {
      if (t === null) return "Not on a sorted diagram";
      if (t === UNSORTED) return "Not sorted yet";
      return this.topicView(tid).s[t].l;
    }

    // hits, best first, as groups, each with its `kind`, label, docs and versions (Map(doc ->
    // versions)):
    // - "subject": {fi, s, holds}, by subject of each family's view (`viewOf`);
    // - "topic", with `tid`: {topic, holds, subject: Map(doc -> its subject's label), models:
    //   Set(family)}, by topic across models in that topic view;
    // - "model": {p, its page id}, for an item outside every family.
    group(hits, items, viewOf, tid) {
      const out = [], byKey = new Map(), first = new Map();
      for (const h of hits) {
        const it = items[h.doc];
        const fi = this.familyOf.has(it.p) ? this.familyOf.get(it.p) : null;
        const same = (fi === null ? "p" + it.p : "f" + fi) + "\u0000" + it.t + "\u0000" + it.k;
        if (first.has(same)) { // the same item in another version: counted, not repeated
          const [g, doc] = first.get(same);
          g.versions.set(doc, (g.versions.get(doc) || 1) + 1);
          continue;
        }
        let gk, g;
        if (fi === null) {
          gk = "p" + it.p;
          g = byKey.get(gk) || { kind: "model", fi: null, p: it.p, s: null, label: null, docs: [], versions: new Map() };
        } else if (tid && this.topics) {
          const dv = this.families[fi].dv, s = this.place(it, fi, dv);
          const t = this.topicOfSubject(fi, s, tid), tv = this.topicView(tid);
          gk = "t/" + t;
          g = byKey.get(gk) || { kind: "topic", fi: null, topic: t, label: this.topicLabel(tid, t),
                                 holds: t !== null && t >= 0 ? tv.s[t].h || "" : "", docs: [], versions: new Map(),
                                 subject: new Map(), models: new Set() };
          if (s !== null) g.subject.set(h.doc, this.label(fi, dv, s));
          g.models.add(fi);
        } else {
          const vid = viewOf(fi), s = this.place(it, fi, vid), v = this.view(fi, vid);
          gk = fi + "/" + v.id + "/" + s;
          g = byKey.get(gk) || { kind: "subject", fi, s, label: this.label(fi, vid, s),
                                 holds: s !== null && s >= 0 ? v.s[s].h || "" : "", docs: [], versions: new Map() };
        }
        if (!byKey.has(gk)) { byKey.set(gk, g); out.push(g); }
        g.docs.push(h.doc);
        first.set(same, [g, h.doc]);
      }
      return out;
    }
  }


  // A diagram's text in pieces, with each "[n]" whose number `tags` knows marked as a link to that
  // shape's element (TR-005): [{text, tag}] (`tag`: the element's key, or absent).
  function tagPieces(text, tags) {
    if (!tags) return [{ text }];
    const out = [];
    let at = 0;
    for (const m of text.matchAll(/\[(\d+)\]/g)) {
      const key = tags[m[1]];
      if (key === undefined) continue;
      if (m.index > at) out.push({ text: text.slice(at, m.index) });
      out.push({ text: m[0], tag: key });
      at = m.index + m[0].length;
    }
    if (at < text.length || !out.length) out.push({ text: text.slice(at) });
    return out;
  }

  // Copies of one element in several models, shown once (plan SH): hits, best first, keep the first
  // copy of each element held elsewhere (an "e" match in its `al`); returns {hits, copies: Map(doc ->
  // how many models hold it)}. Matches by requirement Id or by name are other elements: kept apart.
  function collapseShared(hits, items) {
    const seen = new Map(), copies = new Map(), out = [];
    for (const h of hits) {
      const it = items[h.doc];
      const shared = (it.al || []).some((a) => a[2] === "e");
      if (!shared) { out.push(h); continue; }
      const key = it.t + "\u0000" + it.k;
      if (seen.has(key)) {
        const doc = seen.get(key);
        copies.set(doc, copies.get(doc) + 1);
        continue;
      }
      seen.set(key, h.doc);
      copies.set(h.doc, 1);
      out.push(h);
    }
    return { hits: out, copies };
  }

  // Two models compared (plan SH-05), from the matches their items carry (`al`): each item of A is
  // changed (matched in B, with differences), the same, or only in A; B's items matched in A by
  // none are only in B. Items: requirements, diagrams, packages and elements. Returns {changed:
  // [[docA, keyB, differences]], same, onlyA: [docs], onlyB: [docs]}.
  const COMPARED = new Set(["requirement", "diagram", "package", "element"]);
  function compareModels(items, a, b, tokA, tokB) {
    const out = { changed: [], same: 0, onlyA: [], onlyB: [] };
    const matchedInB = new Set();
    items.forEach((it, d) => {
      if (!COMPARED.has(it.t) || (it.p !== a && it.p !== b)) return;
      const other = it.p === a ? tokB : tokA;
      const m = (it.al || []).find((x) => x[0] === other);
      if (it.p === a) {
        if (!m) out.onlyA.push(d);
        else if (m[3]) out.changed.push([d, m[1], m[3]]);
        else out.same++;
        if (m) matchedInB.add(m[1]);
      } else if (!m) {
        out.onlyB.push(d);
      }
    });
    out.onlyB = out.onlyB.filter((d) => !matchedInB.has(items[d].k));
    return out;
  }

  // The model chooser (plan LN-07): models grouped by folder, by lineage, or listed by name or by
  // date, and what each one is to the others. `projects`: the page's projects, with their facts.
  const HOW = { derived: "derived by others from", "built-on": "built on by others in", root: "shares a root with",
                branches: "a branch beside" };

  function folderOf(p) {
    const path = ((p.sources || [])[0] || {}).path || "";
    const i = path.lastIndexOf("/");
    return i < 0 ? "" : path.slice(0, i).split("!")[0];
  }

  // The note on a model's lineage: its rank among its versions, then its kin and related models.
  function lineageNote(p, labelOf) {
    const out = [];
    if ((p.nv || 1) > 1) out.push(p.rk ? `older version, ${p.nv - p.rk} of ${p.nv}` : `newest of ${p.nv} versions`);
    for (const [t, how] of p.kn || []) out.push(`${HOW[how] || how} ${labelOf(t)}`);
    for (const t of p.rl || []) out.push(`shares a part with ${labelOf(t)}`);
    return out.join("; ");
  }

  // The folder that every model's first path is under ("" for none).
  function commonFolder(projects) {
    const dirs = projects.map(folderOf);
    let common = dirs.length ? dirs[0].split("/") : [];
    for (const d of dirs) {
      const parts = d.split("/");
      let n = 0;
      while (n < common.length && n < parts.length && common[n] === parts[n]) n++;
      common = common.slice(0, n);
    }
    return common.join("/");
  }

  // Groups of page ids, [{title, pids, depth: Map(pid -> indent)}], in display order.
  function chooserGroups(projects, mode) {
    const pids = projects.map((_, i) => i);
    const name = (i) => (projects[i].label || "").toLowerCase();
    if (mode === "name" || mode === "date") {
      const by = mode === "name" ? (a, b) => name(a).localeCompare(name(b))
        : (a, b) => (projects[b].sv || "").localeCompare(projects[a].sv || "") || name(a).localeCompare(name(b));
      return [{ title: null, pids: pids.slice().sort(by), depth: new Map() }];
    }
    if (mode === "folder") {
      const dirs = pids.map((i) => folderOf(projects[i]));
      const cut = commonFolder(projects).length;
      const groups = new Map();
      pids.forEach((i) => {
        const key = dirs[i].slice(cut).replace(/^\//, "") || "(the common folder)";
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(i);
      });
      return [...groups.keys()].sort().map((k) => ({ title: k, pids: groups.get(k).sort((a, b) => name(a).localeCompare(name(b))),
                                                     depth: new Map() }));
    }
    // lineage: clusters joined by family and kin; in each, families newest first, older versions indented
    const byToken = new Map(projects.map((p, i) => [p.token, i]));
    const parent = pids.slice();
    const root = (x) => { while (parent[x] !== x) x = parent[x] = parent[parent[x]]; return x; };
    const join = (a, b) => { if (a !== undefined && b !== undefined) parent[root(a)] = root(b); };
    pids.forEach((i) => {
      const p = projects[i];
      if (p.fm) join(i, byToken.get(p.fm));
      for (const [t] of p.kn || []) join(i, byToken.get(t));
    });
    const clusters = new Map();
    pids.forEach((i) => {
      const r = root(i);
      if (!clusters.has(r)) clusters.set(r, []);
      clusters.get(r).push(i);
    });
    const famKey = (i) => projects[i].fm || projects[i].token;
    const out = [];
    for (const members of clusters.values()) {
      const fams = new Map();
      for (const i of members) {
        if (!fams.has(famKey(i))) fams.set(famKey(i), []);
        fams.get(famKey(i)).push(i);
      }
      const order = [], depth = new Map();
      const famList = [...fams.values()].map((f) => f.sort((a, b) => (projects[a].rk || 0) - (projects[b].rk || 0)));
      famList.sort((a, b) => (projects[a[0]].sv || "").localeCompare(projects[b[0]].sv || "") || name(a[0]).localeCompare(name(b[0])));
      for (const f of famList) f.forEach((i, k) => { order.push(i); depth.set(i, k ? 1 : 0); });
      const kin = members.some((i) => (projects[i].kn || []).length);
      const title = members.length === 1 ? null
        : `${projects[order[0]].label}: ` + (kin ? `${members.length} models built on one another` : `${members.length} versions`);
      out.push({ title, pids: order, depth });
    }
    out.sort((a, b) => name(a.pids[0]).localeCompare(name(b.pids[0])));
    return out;
  }

  // A token as the page's matches name it: its first 16 hex digits (searchpage.page_items' `al`).
  function shortToken(token) {
    return (token || "").replace(/^sha256:/, "").slice(0, 16);
  }

  // How model `there` stands to model `here`, by here's facts: its kin note on there ("derived",
  // "built-on", "root", "branches"), else "older" or "newer" when both are versions of one model;
  // null when neither.
  function standing(here, there) {
    const kin = (here.kn || []).find(([t]) => t === there.token);
    if (kin) return kin[1];
    if (there.fm && there.fm === here.fm) return (there.rk || 0) > (here.rk || 0) ? "older" : "newer";
    return null;
  }

  // A model's metadata, as given to `add --meta`: "key=value" each, once.
  function metadataOf(p) {
    return [...new Set((p.sources || []).flatMap((s) => Object.entries(s.metadata || {}).map(([k, v]) => `${k}=${v}`)))];
  }

  // Items by model and key (`p`, `k`): an element's, requirement's, diagram's or package's doc, and
  // the summaries of it.
  class Lookup {
    constructor() {
      this.byKey = new Map();
      this.sums = new Map();
    }
    add(item, d) {
      const key = item.p + "\u0000" + item.k;
      if (item.t === "summary") {
        if (!this.sums.has(key)) this.sums.set(key, []);
        this.sums.get(key).push(d);
      } else {
        this.byKey.set(key, d);
      }
    }
    doc(pid, key) {
      return this.byKey.get(pid + "\u0000" + key);
    }
    summaries(pid, key) {
      return this.sums.get(pid + "\u0000" + key) || [];
    }
  }

  // What the browse pane shows with no search (plan SB): `families` among the selected models
  // (a Set of page ids, or null for all); one opened (`chosen`), when the selection is narrowed to
  // one or one was chosen; else topics across models, when there are several models and topics,
  // and topics are asked for; else the models' list. Returns {mode: "family" | "topics" | "models",
  // shown: [family indexes], family, narrowed, topics (whether topics can be offered)}.
  function browseMode(families, selected, chosen, by, hasTopics) {
    const shown = families.map((f, fi) => fi).filter((fi) => selected === null || families[fi].p.some((pid) => selected.has(pid)));
    const narrowed = shown.length === 1 && selected !== null;
    const family = narrowed ? shown[0] : chosen;
    const topics = Boolean(hasTopics) && shown.length > 1;
    if (family !== null && family !== undefined && shown.includes(family)) return { mode: "family", shown, family, narrowed, topics };
    return { mode: topics && by === "topic" ? "topics" : "models", shown, family: null, narrowed, topics };
  }

  return { tokens, parse, Field, Index, snippet, mark, decode, decodeText, Subjects, chooserGroups, lineageNote, folderOf,
           commonFolder, tagPieces, collapseShared, compareModels, shortToken, standing, metadataOf, Lookup, browseMode };
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

  const state = { index: new Engine.Index(), projects: [], lookup: new Engine.Lookup(), cancelled: false,
                  subjects: new Engine.Subjects([]), viewOf: new Map(), browse: null, open: new Set(),
                  topicView: null, browseBy: "topic",
                  terms: [], copies: null, // the search shown: its words (marked in the detail pane), its folded copies
                  selected: null, mode: "lineage", // selected: null for every model, else a Set of page ids
                  compare: null }; // [page id, page id]: two models compared (plan SH-05)
  const SHOWN = 3; // results shown a group before "more"
  const UNSORTED = "Not sorted yet", UNSORTED_NOTE = "The LLM gave no answer for these; the next run asks again.";
  const HINT = "Search above; choose a result to read it here.";

  // A link that acts in the page (`onClick`), rather than going anywhere.
  function action(text, onClick, cls) {
    const a = el("a", cls, text);
    a.href = "#";
    a.addEventListener("click", (e) => { e.preventDefault(); onClick(); });
    return a;
  }

  // A link to an item's detail, or the text alone for an item not in the page.
  function itemLink(doc, text) {
    if (doc === undefined) return el("span", null, text);
    const a = el("a", null, text);
    a.href = "#d" + doc;
    return a;
  }

  // Nodes joined by ", ".
  function joined(nodes) {
    return nodes.flatMap((n, i) => (i ? [", ", n] : [n]));
  }

  // A head that opens and closes its body; open ones (`state.open`, by `id`) stay open as the
  // results are drawn again. `fill()` draws the body.
  function collapsible(head, body, id, fill) {
    head.href = "#";
    head.addEventListener("click", (e) => {
      e.preventDefault();
      if (state.open.has(id)) { state.open.delete(id); body.replaceChildren(); } else { state.open.add(id); fill(); }
    });
    if (state.open.has(id)) fill();
  }

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
        state.lookup.add(item, state.index.add(item));
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
    const sb = document.querySelector('script[type="application/octet-stream"][data-subjects]');
    const tb = document.querySelector('script[type="application/octet-stream"][data-topics]');
    if (sb) state.subjects = new Engine.Subjects(await Engine.decode(sb.textContent), tb ? await Engine.decode(tb.textContent) : null);
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
    chooser();
    const types = [...new Set(state.index.items.map((it) => it.t))].sort();
    for (const t of types) $("type").append(new Option(t[0].toUpperCase() + t.slice(1), t));
    let timer = null;
    const go = () => {
      clearTimeout(timer);
      timer = setTimeout(run, 150);
    };
    $("q").addEventListener("input", go);
    $("type").addEventListener("change", run);
    if (state.subjects.families.length) {
      $("grouping").hidden = false;
      if (!state.subjects.topics) $("grouped").querySelector('option[value="topic"]').remove();
      $("grouped").addEventListener("change", run);
    }
    window.addEventListener("hashchange", detail);
    $("q").focus();
    const q = /^#q=(.*)$/.exec(location.hash); // a link can carry a search: page.html#q=REQ-1
    if (q) $("q").value = decodeURIComponent(q[1]);
    run();
    detail();
  }

  function run() {
    const q = $("q").value;
    const list = $("results"), info = $("count");
    list.replaceChildren();
    if (!q.trim()) { // no search: nothing of the last one carries over (CQ-002)
      info.textContent = "";
      state.terms = [];
      state.copies = null;
      if (state.compare) compare(list);
      else browse(list);
      return;
    }
    const t = now();
    const type = $("type").value || null;
    const res = state.index.search(q, { projects: state.selected, type });
    state.terms = res.terms || [];
    const ms = now() - t;
    info.textContent = res.total
      ? `${fmt(res.total)} found (${fmt(res.all)} with every word) in ${(ms / 1000).toFixed(2)} s` +
        (res.total > res.hits.length ? `; the first ${res.hits.length} shown` : "")
      : `Nothing found (${(ms / 1000).toFixed(2)} s)`;
    const shared = Engine.collapseShared(res.hits, state.index.items);
    state.copies = shared.copies;
    const by = state.subjects.families.length ? $("grouped").value : "";
    if (by) {
      const groups = state.subjects.group(shared.hits, state.index.items, viewOf, by === "topic" ? topicId() : null);
      info.textContent += `, in ${count(groups.length, by)}`;
      for (const g of groups) list.append(groupBox(g, res.terms));
    } else {
      for (const h of shared.hits) list.append(resultRow(h, res.terms));
    }
  }

  // What a diagram is about: its generated description, when the tree has one; else nothing.
  function aboutOf(doc) {
    const it = state.index.items[doc];
    const s = state.lookup.summaries(it.p, it.k)[0];
    return s === undefined ? "" : state.index.items[s].x || "";
  }

  // The model chooser (plan LN-07): which models search and browsing cover.
  const labelOf = (token) => {
    const i = state.projects.findIndex((p) => p.token === token);
    return i < 0 ? token.slice(0, 15) : state.projects[i].label;
  };
  function chooserLabel() {
    const n = state.projects.length, k = state.selected === null ? n : state.selected.size;
    $("models").textContent = `Models: ${k === n ? `all ${n}` : `${k} of ${n}`} ▾`;
  }
  function chooser() {
    const panel = $("chooser"), list = $("mlist");
    chooserLabel();
    $("models").addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      if (!panel.hidden) { fill(); $("mfilter").focus(); }
    });
    $("mclose").addEventListener("click", () => { panel.hidden = true; });
    $("mgroup").addEventListener("change", () => { state.mode = $("mgroup").value; fill(); });
    $("mfilter").addEventListener("input", fill);
    const visible = () => [...list.querySelectorAll("input[data-pid]")].filter((c) => !c.closest(".mrow").hidden)
      .map((c) => Number(c.dataset.pid));
    const select = (set) => {
      state.selected = set.size === state.projects.length ? null : set;
      if (!state.selected || state.selected.size !== 2) state.compare = null;
      $("mcompare").disabled = !state.selected || state.selected.size !== 2;
      chooserLabel();
      fill();
      state.browse = null;
      run();
    };
    const choose = (pids, on) => {
      const set = state.selected === null ? new Set(state.projects.map((_, i) => i)) : new Set(state.selected);
      for (const i of pids) (on ? set.add(i) : set.delete(i));
      select(set);
    };
    $("mcompare").addEventListener("click", () => {
      if (!state.selected || state.selected.size !== 2) return;
      const [a, b] = [...state.selected].sort((x, y) => (state.projects[x].sv || "").localeCompare(state.projects[y].sv || "") || x - y);
      state.compare = [a, b]; // the older first
      panel.hidden = true;
      $("q").value = "";
      run();
    });
    $("mall").addEventListener("click", () => choose(visible(), true));
    $("mnone").addEventListener("click", () => choose(visible(), false));
    $("mnewest").addEventListener("click", () => { // of the models shown: the newest versions on, the older off
      const set = state.selected === null ? new Set(state.projects.map((_, i) => i)) : new Set(state.selected);
      for (const i of visible()) (state.projects[i].rk ? set.delete(i) : set.add(i));
      select(set);
    });
    const common = Engine.commonFolder(state.projects);
    const shortFolder = (p) => Engine.folderOf(p).slice(common.length).replace(/^\//, "") || "(the common folder)";
    function fill() {
      const words = $("mfilter").value.toLowerCase().split(/\s+/).filter(Boolean);
      const isOn = (i) => state.selected === null || state.selected.has(i);
      list.replaceChildren();
      for (const g of Engine.chooserGroups(state.projects, state.mode)) {
        const box = el("div", "mgroup");
        const rows = g.pids.map((i) => {
          const p = state.projects[i];
          const row = el("label", "mrow" + (g.depth.get(i) ? " older" : ""));
          const cb = el("input");
          cb.type = "checkbox";
          cb.dataset.pid = String(i);
          cb.checked = isOn(i);
          cb.addEventListener("change", () => choose([i], cb.checked));
          const c = p.counts || {};
          const facts = [p.sv ? `saved ${p.sv.slice(0, 10)}` : null, p.ex, c.diagram ? count(c.diagram, "diagram") : null,
                         c.requirement ? count(c.requirement, "requirement") : null].filter(Boolean).join(" · ");
          const meta = Engine.metadataOf(p);
          const head = el("div", "mhead");
          head.append(cb, el("span", "mname", p.label), el("span", "mfacts", facts));
          const where = el("div", "mwhere", [shortFolder(p), meta.join(", ")].filter(Boolean).join(" · "));
          where.title = (p.sources || []).map((s) => s.path).join("\n");
          row.append(head, where);
          const note = Engine.lineageNote(p, labelOf);
          if (note) {
            const n = el("div", "mnote", note);
            n.title = note; // in full, on hover
            row.append(n);
          }
          const hay = [p.label, p.name, ...(p.sources || []).map((s) => s.path), ...meta, note].join(" ").toLowerCase();
          row.hidden = !words.every((w) => hay.includes(w));
          return row;
        });
        if (rows.every((r) => r.hidden)) continue;
        if (g.title) {
          const head = el("label", "mgroup-head");
          const cb = el("input");
          cb.type = "checkbox";
          cb.checked = g.pids.every(isOn);
          cb.indeterminate = !cb.checked && g.pids.some(isOn);
          cb.addEventListener("change", () => choose(g.pids, cb.checked));
          head.append(cb, el("span", null, g.title));
          box.append(head);
        }
        box.append(...rows);
        list.append(box);
      }
    }
  }

  // How two compared models stand (`Engine.standing` of the second to the first).
  const PAIR = { derived: "the first was built on the second, by others", "built-on": "the second was built on the first, by others",
                 root: "rivals on a shared root", branches: "branches of one model", older: "versions of one model",
                 newer: "versions of one model" };

  // Two models compared (plan SH-05): what changed, and what is only in one, by kind.
  function compare(list) {
    const [a, b] = state.compare, A = state.projects[a], B = state.projects[b];
    const res = Engine.compareModels(state.index.items, a, b, Engine.shortToken(A.token), Engine.shortToken(B.token));
    const top = el("div", "browse-head");
    const close = action("Close the comparison", () => { state.compare = null; run(); });
    const how = PAIR[Engine.standing(A, B)] || "";
    top.append(el("strong", null, "Comparing"), " ", A.label, " with ", B.label, how ? ` (${how})` : "", " · ", close);
    list.append(top, el("p", "browse-lead",
      `${count(res.changed.length, "item")} changed, ${fmt(res.onlyA.length)} only in the first, ` +
      `${fmt(res.onlyB.length)} only in the second, ${fmt(res.same)} the same. In what changed, "here" is the ` +
      `first, "there" the second.`));
    const type = $("type").value || null;
    const sections = [
      ["Changed", res.changed.map(([d, , diff]) => ({ d, diff }))],
      [`Only in ${A.label}`, res.onlyA.map((d) => ({ d }))],
      [`Only in ${B.label}`, res.onlyB.map((d) => ({ d }))],
    ];
    for (const [title, rows0] of sections) {
      const rows = rows0.filter((r) => !type || state.index.items[r.d].t === type);
      const kinds = new Map();
      for (const r of rows) {
        const t = state.index.items[r.d].t;
        if (!kinds.has(t)) kinds.set(t, []);
        kinds.get(t).push(r);
      }
      for (const [t, rs] of [...kinds].sort((x, y) => x[0].localeCompare(y[0]))) {
        const box = el("section", "group");
        const head = el("a", "group-head");
        head.append(el("span", "group-label", `${title}: ${t}s`), el("span", "group-count", fmt(rs.length)));
        const body = el("div");
        const fill = (n) => {
          body.replaceChildren(...rs.slice(0, n).map((r) => resultRow({ doc: r.d }, [], r.diff || undefined)));
          if (rs.length > n) {
            const more = el("button", "more", `${fmt(rs.length - n)} more`);
            more.type = "button";
            more.addEventListener("click", () => fill(n + 200));
            body.append(more);
          }
        };
        collapsible(head, body, `cmp/${title}/${t}`, () => fill(200));
        box.append(head, body);
        list.append(box);
      }
    }
  }

  const viewOf = (fi) => state.viewOf.get(fi) || state.subjects.families[fi].dv;
  const topicId = () => state.subjects.topicView(state.topicView).id;

  // A group of results: its subject, its model when the page has several, its best few, and the rest on request.
  function groupBox(g, terms) {
    const box = el("section", "group");
    const head = el("div", "group-head");
    head.append(el("span", "group-label", g.kind === "model" ? state.projects[g.p].label : g.label));
    if (g.kind === "subject" && state.subjects.families.length > 1) head.append(el("span", "group-model", state.subjects.families[g.fi].n));
    if (g.kind === "topic") head.append(el("span", "group-model", `in ${count(g.models.size, "model")}`));
    head.append(el("span", "group-count", count(g.docs.length, "result")));
    if (g.holds) head.title = g.holds;
    box.append(head);
    const rows = g.docs.map((doc) => {
      const r = resultRow({ doc }, terms);
      const n = g.versions.get(doc);
      if (n) r.querySelector(".result-where").append(` · in ${n} versions`);
      if (g.subject && g.subject.has(doc)) r.querySelector(".result-head").append(el("span", "result-subject", g.subject.get(doc)));
      return r;
    });
    box.append(...rows.slice(0, SHOWN));
    if (rows.length > SHOWN) {
      const more = el("button", "more", `${rows.length - SHOWN} more`);
      more.type = "button";
      more.addEventListener("click", () => more.replaceWith(...rows.slice(SHOWN)));
      box.append(more);
    }
    return box;
  }

  // With no search: the models' subjects to browse. A model, then a view of it, then its subjects,
  // each opening its diagrams.
  function browse(list) {
    const sb = state.subjects;
    if (!sb.families.length) {
      list.append(el("p", "hint", HINT));
      return;
    }
    const mode = Engine.browseMode(sb.families, state.selected, state.browse, state.browseBy, sb.topics);
    if (mode.mode === "topics") {
      browseTopics(list, mode.shown);
      return;
    }
    if (mode.mode === "models") {
      const lead = el("p", "browse-lead", "Search above, or browse a model by subject");
      if (mode.topics) lead.append(" (or ", switchTo("topic", "topics across models"), ")");
      list.append(lead);
      mode.shown.forEach((fi) => {
        const f = sb.families[fi];
        const row = action(null, () => { state.browse = fi; run(); }, "result");
        const head = el("div", "result-head");
        head.append(el("span", "result-name", f.n));
        row.append(head, el("div", "result-where", `${count(Object.keys(f.k).length, "diagram")}` +
          (f.p.length > 1 ? `, ${f.p.length} versions` : "") + `, ${count(f.v.length, "view")}`));
        list.append(row);
      });
      return;
    }
    const chosen = mode.family, f = sb.families[chosen], v = sb.view(chosen, viewOf(chosen));
    const top = el("div", "browse-head");
    if (!mode.narrowed) {
      top.append(action(mode.topics && state.browseBy === "topic" ? "Topics" : "All models", () => { state.browse = null; run(); }), " › ");
    }
    top.append(el("strong", null, f.n));
    const pick = el("select");
    pick.setAttribute("aria-label", "View");
    for (const w of f.v) pick.append(new Option(w.t + (w.id === f.dv ? " (suggested)" : ""), w.id, false, w.id === v.id));
    pick.addEventListener("change", () => { state.viewOf.set(chosen, pick.value); run(); });
    top.append(" ", pick);
    list.append(top);
    const subjects = v.s.map((s, si) => ({ label: s.l, holds: s.h || "", keys: s.d, si }));
    if (v.u && v.u.length) subjects.push({ label: UNSORTED, holds: UNSORTED_NOTE, keys: v.u, si: -1 });
    for (const s of subjects) list.append(subjectBox(f, s.label, s.holds, s.keys, `${chosen}/${v.id}/${s.si}`));
  }

  // A subject to open: its diagrams, by name. `model`: its model's name, shown beside its label.
  function subjectBox(f, label, holds, keys, id, model) {
    const box = el("section", "group");
    const head = el("a", "group-head");
    head.append(el("span", "group-label", label));
    if (model) head.append(el("span", "group-model", model));
    head.append(el("span", "group-count", count(keys.length, "diagram")));
    if (holds) head.title = holds;
    const body = el("div");
    collapsible(head, body, id, () => {
      body.replaceChildren(...keys.map((k) => state.lookup.doc(f.k[k], k)).filter((d) => d !== undefined)
        .sort((a, b) => (state.index.items[a].n || "").localeCompare(state.index.items[b].n || ""))
        .map((doc) => resultRow({ doc }, [], aboutOf(doc))));
    });
    box.append(head, body);
    return box;
  }

  function switchTo(by, text) {
    return action(text, () => { state.browseBy = by; run(); });
  }

  // With no search and several models: topics across models (plan SB CP4), each opening the
  // subjects it gathers (a model's subject in its suggested view), each opening its diagrams.
  function browseTopics(list, shown) {
    const sb = state.subjects, tv = sb.topicView(state.topicView), keep = new Set(shown);
    const lead = el("p", "browse-lead", "Search above, or browse topics across models (or ");
    lead.append(switchTo("model", "a model by subject"), ")");
    list.append(lead);
    if (sb.topics.v.length > 1) {
      const top = el("div", "browse-head");
      const pick = el("select");
      pick.setAttribute("aria-label", "Topics");
      for (const w of sb.topics.v) pick.append(new Option(w.t + (w.id === sb.topics.dv ? " (suggested)" : ""), w.id, false, w.id === tv.id));
      pick.addEventListener("change", () => { state.topicView = pick.value; run(); });
      top.append(pick);
      list.append(top);
    }
    const topics = tv.s.map((t, ti) => ({ label: t.l, holds: t.h || "", m: t.m, ti }));
    if (tv.u && tv.u.length) topics.push({ label: UNSORTED, holds: UNSORTED_NOTE, m: tv.u, ti: -1 });
    for (const t of topics) {
      const members = t.m.filter(([fi]) => keep.has(fi));
      if (!members.length) continue;
      const box = el("section", "group topic");
      const head = el("a", "group-head");
      const models = new Set(members.map(([fi]) => fi)).size;
      head.append(el("span", "group-label", t.label), el("span", "group-count",
        `${count(members.length, "subject")} in ${count(models, "model")}`));
      if (t.holds) head.title = t.holds;
      const id = `t/${tv.id}/${t.ti}`;
      const body = el("div", "topic-body");
      collapsible(head, body, id, () => {
        body.replaceChildren(...members.map(([fi, si]) => {
          const f = sb.families[fi], v = sb.view(fi, f.dv), s = v.s[si];
          return subjectBox(f, s.l, s.h || "", s.d, `${id}/${fi}/${si}`, f.n);
        }));
      });
      box.append(head, body);
      list.append(box);
    }
  }

  function badge(it) {
    if (it.t === "summary") return `${it.kd || "Summary"} (generated)`;
    return it.kd || it.t;
  }

  // A result's row; `text` in place of the snippet's source (browsing shows what a diagram is about).
  function resultRow(h, terms, text) {
    const it = state.index.items[h.doc];
    const row = el("a", "result");
    row.href = "#d" + h.doc;
    const head = el("div", "result-head");
    head.append(el("span", "badge", badge(it)), el("span", "result-name", it.n || it.k));
    if (it.id && !(it.n || "").includes(it.id)) head.append(el("span", "result-id", it.id));
    const n = state.copies && state.copies.get(h.doc);
    row.append(head, el("div", "result-where", `${state.projects[it.p].label}${n > 1 ? ` and ${n - 1} more` : ""}` +
                                               `${it.w ? " · " + it.w : ""}`));
    const snip = el("div", "result-snippet");
    for (const piece of Engine.snippet(text !== undefined ? text : it.x || it.c || "", terms)) snip.append(piece.mark ? el("mark", null, piece.text) : piece.text);
    row.append(snip);
    return row;
  }

  function link(pid, key, label) {
    return itemLink(state.lookup.doc(pid, key), label);
  }

  function section(title, body) {
    const s = el("section", "detail-section");
    s.append(el("h3", null, title), body);
    return s;
  }

  // Text, with the search's words marked, and a diagram's "[n]" tags as links to their shapes'
  // elements, when `tags` are given and the element is in the page (TR-005). Nodes, never HTML.
  function textBlock(text, tags, pid) {
    const pre = el("pre", "text");
    for (const piece of Engine.mark(text, state.terms)) {
      for (const part of Engine.tagPieces(piece.text, tags)) {
        const d = part.tag === undefined ? undefined : state.lookup.doc(pid, part.tag);
        let node;
        if (d !== undefined) {
          node = el("a", "tag", part.text);
          node.href = "#d" + d;
          node.title = state.index.items[d].n || part.tag;
        } else {
          node = document.createTextNode(part.text);
        }
        pre.append(piece.mark ? (() => { const m = el("mark"); m.append(node); return m; })() : node);
      }
    }
    return pre;
  }

  // The same item in other models (plan SH): each a link, with how it matches and what differs there.
  const MATCH = { e: "the same element", i: "the same requirement Id", n: "the same name" };
  // What another model is to this one (`Engine.standing`).
  const THERE = { derived: "this one was built on it", "built-on": "built on this one, by others",
                  root: "a rival on a shared root", branches: "a branch beside this one", older: "an older version",
                  newer: "a newer version" };
  function alsoIn(it) {
    const ul = el("ul", "relations");
    for (const [tok, key, basis, diff] of it.al) {
      const pid = state.projects.findIndex((p) => Engine.shortToken(p.token) === tok);
      const li = el("li");
      li.append(itemLink(pid < 0 ? undefined : state.lookup.doc(pid, key), pid < 0 ? tok : state.projects[pid].label));
      const how = pid < 0 ? "" : THERE[Engine.standing(state.projects[it.p], state.projects[pid])] || "";
      if (how) li.append(el("span", "phrase", ` (${how})`));
      li.append(el("span", "phrase", ` ${MATCH[basis] || basis}: `), diff || "the same");
      ul.append(li);
    }
    return ul;
  }

  // The number tags that a diagram's texts use: its own; a summary's, its diagram's.
  function tagsOf(it) {
    if (it.tg) return it.tg;
    if (it.t === "summary" && it.of) {
      const d = state.lookup.doc(it.p, it.of[0]);
      return d === undefined ? undefined : state.index.items[d].tg;
    }
    return undefined;
  }

  function detail() {
    const pane = $("detail");
    const m = /^#d(\d+)$/.exec(location.hash);
    if (!m) {
      pane.replaceChildren(el("p", "hint", HINT));
      return;
    }
    const it = state.index.items[Number(m[1])];
    const pid = it ? it.p : -1, project = state.projects[pid];
    if (!it || !project) {
      pane.replaceChildren(el("p", "hint", "That item isn't in this page."));
      return;
    }
    const out = [el("h2", null, it.n || it.k), el("div", "badges"), factsTable(it, pid, project)];
    out[1].append(el("span", "badge", badge(it)));
    if (it.al && it.al.length) out.push(section("Also in", alsoIn(it)));
    if (it.sk && it.sk.length) out.push(section("Sketch", sketchBox(it)));
    const tags = tagsOf(it);
    if (it.x) out.push(section(it.t === "requirement" ? "Requirement text" : it.t === "summary" ? "Summary" : "Text",
                               textBlock(it.x, tags, pid)));
    if (it.r && it.r.length) out.push(section("Relationships", relations(it.r, pid)));
    if (it.d && it.d.length) {
      const p = el("p");
      p.append(...joined(it.d.map(([k, label]) => link(pid, k, label))));
      out.push(section("Shown in diagrams", p));
    }
    out.push(...summaries(it, pid, tags));
    if (it.c) {
      const body = el("div");
      body.append(el("p", "hint", "Everything this page searches for this item: its text, where it is, and what it relates to."),
                  textBlock(it.c, tags, pid));
      out.push(section("Full text", body));
    }
    pane.replaceChildren(...out);
    pane.scrollTop = 0;
  }

  // An item's facts: its ids, where it is, its model (saved when, by which Cameo, its lineage), its
  // subject, source and metadata, what generated it, and what lists it.
  function factsTable(it, pid, project) {
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
    fact("Model saved", [project.sv && project.sv.slice(0, 10), project.ex].filter(Boolean).join(", "));
    fact("Lineage", Engine.lineageNote(project, labelOf));
    const fi = state.subjects.familyOf.get(pid);
    if (fi !== undefined && it.t !== "summary") {
      const vid = viewOf(fi), s = state.subjects.place(it, fi, vid);
      if (s !== null) fact("Subject", `${state.subjects.label(fi, vid, s)} (${state.subjects.view(fi, vid).t})`);
    }
    fact("Source", (project.sources || []).map((s) => s.path).join("; "));
    fact("Metadata", Engine.metadataOf(project).join("; "));
    if (it.m) fact("Generated by", `${it.m}; not part of the source model`);
    if (it.l) fact("Listed in", link(pid, it.l[0], it.l[1]));
    return facts;
  }

  // An item's relationships, grouped by how they read ("satisfied by", "derived from"...), each a link.
  function relations(rels, pid) {
    const groups = new Map();
    for (const [, , phrase, okey, olabel] of rels) {
      if (!groups.has(phrase)) groups.set(phrase, []);
      groups.get(phrase).push(link(pid, okey, olabel));
    }
    const ul = el("ul", "relations");
    for (const [phrase, links] of groups) {
      const li = el("li");
      li.append(el("span", "phrase", phrase + " "), ...joined(links));
      ul.append(li);
    }
    return ul;
  }

  // The generated summaries of an item, marked as such.
  function summaries(it, pid, tags) {
    if (it.t === "summary") return [];
    return state.lookup.summaries(pid, it.k).map((d) => state.index.items[d]).map((s) => {
      const body = el("div");
      body.append(el("p", "generated", `Generated by ${s.m}; not part of the source model.`), textBlock(s.x, tags, pid));
      return section((s.kd || "Summary") + (s.pt ? ", " + s.pt : ""), body);
    });
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
      frame.addEventListener("click", (e) => { // a shape opens its element; anywhere else zooms
        const shape = e.target.closest ? e.target.closest("g.linked[data-k]") : null;
        const d = shape ? state.lookup.doc(it.p, shape.getAttribute("data-k")) : undefined;
        if (d !== undefined) location.hash = "#d" + d;
        else frame.classList.toggle("zoomed");
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
        const shown = document.importNode(svg, true); // a copy: listeners go on the frame, above
        for (const g of shown.querySelectorAll("[data-k]")) {
          if (state.lookup.doc(it.p, g.getAttribute("data-k")) !== undefined) g.classList.add("linked");
        }
        frame.replaceChildren(shown);
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
