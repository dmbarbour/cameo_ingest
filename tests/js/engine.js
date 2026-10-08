// The page's engine on a small corpus: queries, prefixes, phrases, filters, snippets; then an item's
// "[n]" tags, copies across models shown once, and two models compared.
const assert = require("assert");
const Engine = require("../../src/cameo_ingest/assets/search.js");

assert.deepStrictEqual(Engine.tokens("Valve REQ-1-OAD-1050, v1.2 ok."), ["valve", "req-1-oad-1050", "v1.2", "ok"]);
assert.deepStrictEqual(Engine.parse('"leak signal" valve REQ-1-OAD-10*').groups.map((g) => [g.token, g.prefix]),
  [["valve", false], ["req-1-oad-10", true], ["leak", false], ["signal", false]]);

const ix = new Engine.Index();
const items = [
  { t: "requirement", p: 0, id: "REQ-1-OAD-1050", n: "Focal length", x: "The focal length shall be 450 m." },
  { t: "requirement", p: 0, id: "REQ-1-OAD-1051", n: "Plate scale", x: "Plate scale of 0.4 arcsec/mm at the focal plane." },
  { t: "element", p: 1, n: "Brine Valve K7", x: "Closes within 340 milliseconds of a leak signal." },
  { t: "element", p: 1, n: "Pump Station", x: "Two pumps, Otter and Heron; a valve upstream." },
  { t: "summary", p: 1, n: "Summary of Pumps", x: "The valve and the pumps." },
];
items.forEach((it) => ix.add(it));
ix.finish();
const names = (res) => res.hits.map((h) => ix.items[h.doc].n);

// An id is one token, found whole, and by a prefix.
assert.deepStrictEqual(names(ix.search("REQ-1-OAD-1050")), ["Focal length"]);
assert.deepStrictEqual(names(ix.search("req-1-oad-105*")).sort(), ["Focal length", "Plate scale"]);
// Items holding every word come first; a name outweighs text.
let res = ix.search("valve leak");
assert.strictEqual(names(res)[0], "Brine Valve K7");
assert.strictEqual(res.all, 1);
assert.strictEqual(res.total, 3);
assert.strictEqual(names(ix.search("valve"))[0], "Brine Valve K7");
// A phrase must appear as written.
assert.deepStrictEqual(names(ix.search('"leak signal"')), ["Brine Valve K7"]);
assert.deepStrictEqual(names(ix.search('"signal leak"')), []);
// Filters by project and type.
assert.deepStrictEqual(names(ix.search("valve", { type: "summary" })), ["Summary of Pumps"]);
assert.deepStrictEqual(names(ix.search("focal", { project: 1 })), []);
// Snippets mark the words; nothing is found for nothing.
assert.deepStrictEqual(Engine.mark("A Valve, a valve", ["valve"]).filter((p) => p.mark).length, 2);
assert.strictEqual(Engine.snippet("x".repeat(500) + " valve here", ["valve"])[0].text.startsWith("…"), true);
assert.strictEqual(ix.search("").total, 0);
// A diagram's "[n]" tags (TR-005): known numbers become links, others stay text.
assert.deepStrictEqual(Engine.tagPieces("[1] «Block» Pump; [2] Valve; [9] ghost.", { 1: "k1", 2: "k2" }),
  [{ text: "[1]", tag: "k1" }, { text: " «Block» Pump; " }, { text: "[2]", tag: "k2" }, { text: " Valve; [9] ghost." }]);
assert.deepStrictEqual(Engine.tagPieces("no tags", undefined), [{ text: "no tags" }]);
assert.deepStrictEqual(Engine.tagPieces("[1]", { 1: "k" }), [{ text: "[1]", tag: "k" }]);
// Copies of one element in several models, shown once (plan SH).
{
  const items = [
    { t: "requirement", k: "r1", p: 0, al: [["bbbb", "r1", "e", ""]] },
    { t: "requirement", k: "r1", p: 1, al: [["aaaa", "r1", "e", ""]] },
    { t: "requirement", k: "r9", p: 1, al: [["aaaa", "r8", "i", "text"]] }, // another element, the same Id
    { t: "element", k: "x", p: 0 },
  ];
  const got = Engine.collapseShared([{ doc: 1 }, { doc: 0 }, { doc: 2 }, { doc: 3 }], items);
  assert.deepStrictEqual(got.hits.map((h) => h.doc), [1, 2, 3]);
  assert.strictEqual(got.copies.get(1), 2);
}
// Two models compared (plan SH-05).
{
  const items = [
    { t: "requirement", k: "r1", p: 0, al: [["bbbb", "r1", "e", "text"]] }, // changed
    { t: "requirement", k: "r2", p: 0, al: [["bbbb", "r2", "e", ""]] }, // the same
    { t: "element", k: "x", p: 0 }, // only in A
    { t: "requirement", k: "r1", p: 1, al: [["aaaa", "r1", "e", "text"]] },
    { t: "requirement", k: "r2", p: 1, al: [["aaaa", "r2", "e", ""]] },
    { t: "diagram", k: "d9", p: 1 }, // only in B
    { t: "summary", k: "r1", p: 1 }, // not compared
  ];
  const c = Engine.compareModels(items, 0, 1, "aaaa", "bbbb");
  assert.deepStrictEqual(c.changed, [[0, "r1", "text"]]);
  assert.strictEqual(c.same, 1);
  assert.deepStrictEqual(c.onlyA, [2]);
  assert.deepStrictEqual(c.onlyB, [5]);
}
// A model's short token, standing, metadata; items by model and key; the browse mode (CQ-020).
assert.strictEqual(Engine.shortToken("sha256:0123456789abcdef0123"), "0123456789abcdef");
assert.strictEqual(Engine.shortToken("0123456789abcdef0123"), "0123456789abcdef");
{
  const tender = { token: "t", fm: "t", rk: 0 }, bid = { token: "b", fm: "b2", rk: 1, kn: [["t", "derived"]] };
  const bid2 = { token: "b2", fm: "b2", rk: 0, kn: [["t", "derived"]] };
  assert.strictEqual(Engine.standing(bid, tender), "derived");
  assert.strictEqual(Engine.standing(bid2, bid), "older");
  assert.strictEqual(Engine.standing(bid, bid2), "newer");
  assert.strictEqual(Engine.standing(tender, bid2), null);
  assert.deepStrictEqual(Engine.metadataOf({ sources: [{ metadata: { by: "A" } }, { metadata: { by: "A", ver: "2" } }] }),
                         ["by=A", "ver=2"]);
  const lk = new Engine.Lookup();
  lk.add({ p: 0, k: "e1", t: "element" }, 5);
  lk.add({ p: 0, k: "e1", t: "summary" }, 6);
  assert.strictEqual(lk.doc(0, "e1"), 5);
  assert.deepStrictEqual(lk.summaries(0, "e1"), [6]);
  assert.strictEqual(lk.doc(1, "e1"), undefined);
  const fams = [{ p: [0, 1] }, { p: [2] }];
  assert.strictEqual(Engine.browseMode(fams, null, null, "topic", true).mode, "topics");
  assert.strictEqual(Engine.browseMode(fams, null, null, "model", true).mode, "models");
  assert.strictEqual(Engine.browseMode(fams, null, null, "topic", false).mode, "models");
  assert.deepStrictEqual(Engine.browseMode(fams, null, 1, "topic", true).family, 1);
  const one = Engine.browseMode(fams, new Set([2]), null, "topic", true);  // narrowed to one model: opened
  assert.strictEqual(one.mode, "family");
  assert.strictEqual(one.family, 1);
  assert.strictEqual(one.narrowed, true);
  assert.strictEqual(one.topics, false);
}
console.log("ok");
