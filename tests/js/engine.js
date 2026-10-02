// The page's engine on a small corpus: queries, prefixes, phrases, filters, snippets.
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
console.log("ok");
