// BM25 scores of the page's engine, for comparison with harness.BM25: node bm25.js INPUT.json
// INPUT: {"texts": [...], "queries": [...]}; prints a list of score lists, one per query.
const fs = require("fs");
const Engine = require("../../src/cameo_ingest/assets/search.js");
const { texts, queries } = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const f = new Engine.Field();
texts.forEach((t, d) => f.add(d, t));
f.finish(texts.length);
const out = queries.map((q) => {
  const into = new Float64Array(texts.length), hit = new Uint8Array(texts.length);
  for (const t of new Set(Engine.tokens(q))) f.score(t, 1, into, hit);
  return Array.from(into);
});
console.log(JSON.stringify(out));
