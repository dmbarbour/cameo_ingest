// Subjects in the page (plan SB-07c): node subjects.js [PAGE.html QUERY]
// Without arguments, checks the engine on a made-up family; with a page, groups a search of it
// and prints {"hits", "grouped", "groups", "families"}.
const pagedata = require("./pagedata");
const assert = require("assert");
const Engine = require("../../src/cameo_ingest/assets/search.js");

if (process.argv.length < 4) {
  // One family of two versions (page ids 0, newest, and 1) and a model alone (2).
  const fams = [{ n: "M", p: [0, 1], dv: "ways-1", k: { d1: 0, d2: 0, d3: 1 }, vs: { d1: 2 },
                  v: [{ id: "ways-1", t: "By part", kd: "llm", s: [{ l: "Pumps", h: "the pumps", d: ["d1"] }, { l: "Valves", d: ["d2"] }],
                        u: ["d3"] },
                      { id: "packages", t: "By package", kd: "packages", s: [{ l: "All", d: ["d1", "d2", "d3"] }] }] }];
  const sb = new Engine.Subjects(fams);
  const items = [
    { p: 0, t: "diagram", k: "d1" }, { p: 1, t: "diagram", k: "d1" }, // the same diagram in two versions
    { p: 0, t: "element", k: "e1", d: [["d2", "D2"], ["d1", "D1"], ["d2", "D2"]] }, // mostly on Valves
    { p: 0, t: "diagram", k: "d3" }, // unsorted
    { p: 0, t: "element", k: "e2", d: [] }, // on no diagram
    { p: 2, t: "element", k: "x" }, // outside every family
  ];
  assert.strictEqual(sb.place(items[0], 0, "ways-1"), 0);
  assert.strictEqual(sb.place(items[2], 0, "ways-1"), 1);
  assert.strictEqual(sb.place(items[3], 0, "ways-1"), -1);
  assert.strictEqual(sb.place(items[4], 0, "ways-1"), null);
  assert.strictEqual(sb.place(items[2], 0, "packages"), 0);
  const groups = sb.group(items.map((_, doc) => ({ doc })), items, () => "ways-1");
  assert.deepStrictEqual(groups.map((g) => g.label), ["Pumps", "Valves", "Not sorted yet", "Not on a sorted diagram", null]);
  assert.deepStrictEqual(groups[0].docs, [0]); // its copy in the older version, counted
  assert.strictEqual(groups[0].versions.get(0), 2);
  assert.strictEqual(groups[0].holds, "the pumps");
  assert.strictEqual(groups[4].p, 2);

  // Topics across models (plan SB CP4): two families, each subject of a default view in a topic.
  const two = [fams[0], { n: "N", p: [2], dv: "ways-1", k: { n1: 2, n2: 2 },
                          v: [{ id: "ways-1", t: "By part", kd: "llm", s: [{ l: "Pumps too", d: ["n1"] }, { l: "Other", d: ["n2"] }] }] }];
  const topics = { dv: "llm", v: [{ id: "llm", t: "Topics", kd: "llm", s: [{ l: "Pumping", h: "pumps", m: [[0, 0], [1, 0]] }, { l: "Valving", m: [[0, 1]] }],
                                    u: [[1, 1]] },
                                  { id: "words", t: "Words", kd: "words", s: [{ l: "pump, valve", m: [[0, 0], [0, 1], [1, 0], [1, 1]] }] }] };
  const tp = new Engine.Subjects(two, topics);
  const its = [{ p: 0, t: "diagram", k: "d1" }, { p: 2, t: "diagram", k: "n1" }, { p: 0, t: "element", k: "e1", d: [["d2", "D2"]] },
               { p: 2, t: "diagram", k: "n2" }, { p: 0, t: "diagram", k: "d3" }, { p: 0, t: "element", k: "e2", d: [] }];
  assert.strictEqual(tp.topic(its[0], 0, null), 0);
  assert.strictEqual(tp.topic(its[1], 1, null), 0);
  assert.strictEqual(tp.topic(its[2], 0, null), 1); // an element: by its subject
  assert.strictEqual(tp.topic(its[3], 1, null), -1); // its subject unsorted in the topics
  assert.strictEqual(tp.topic(its[4], 0, null), -1); // its own diagram unsorted in the family
  assert.strictEqual(tp.topic(its[5], 0, null), null); // on no diagram
  assert.strictEqual(tp.topic(its[1], 1, "words"), 0);
  const tg = tp.group(its.map((_, doc) => ({ doc })), its, (fi) => two[fi].dv, "llm");
  assert.deepStrictEqual(tg.map((g) => g.label), ["Pumping", "Valving", "Not sorted yet", "Not on a sorted diagram"]);
  assert.deepStrictEqual(tg[0].docs, [0, 1]);
  assert.strictEqual(tg[0].models.size, 2);
  assert.strictEqual(tg[0].subject.get(1), "Pumps too");
  assert.strictEqual(tg[0].holds, "pumps");
  assert.strictEqual(new Engine.Subjects(two, null).topics, null);
  console.log("ok");
  return;
}

(async () => {
  const data = await pagedata.read(process.argv[2]);
  const ix = pagedata.index(data.projects);
  const sb = new Engine.Subjects(data.subjects || [], data.topics);
  const res = ix.search(process.argv[3]);
  const groups = sb.group(res.hits, ix.items, (fi) => sb.families[fi].dv);
  const grouped = groups.reduce((n, g) => n + g.docs.length + [...g.versions.values()].reduce((a, v) => a + v - 1, 0), 0);
  const order = groups.map((g) => res.hits.findIndex((h) => h.doc === g.docs[0]));
  console.log(JSON.stringify({ hits: res.hits.length, grouped, groups: groups.length, families: sb.families.length,
                               ordered: order.every((x, i) => i === 0 || x > order[i - 1]),
                               labels: groups.slice(0, 5).map((g) => g.label) }));
})();
