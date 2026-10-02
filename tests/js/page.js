// A written page's data, unpacked and indexed as a browser would: node page.js PAGE.html QUERY
// Prints {"projects": n, "items": n, "names": [the first hits' names]}.
const fs = require("fs");
const Engine = require("../../src/cameo_ingest/assets/search.js");
(async () => {
  const html = fs.readFileSync(process.argv[2], "utf8");
  const blocks = [...html.matchAll(/<script type="application\/octet-stream"[^>]*>([^<]*)<\/script>/g)];
  const ix = new Engine.Index();
  for (const [i, b] of blocks.entries()) {
    const data = await Engine.decode(b[1]);
    for (const it of data.items) {
      it.p = i;
      ix.add(it);
    }
  }
  ix.finish();
  const res = ix.search(process.argv[3]);
  console.log(JSON.stringify({ projects: blocks.length, items: ix.items.length,
                               names: res.hits.slice(0, 5).map((h) => ix.items[h.doc].n) }));
})();
