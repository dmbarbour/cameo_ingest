// A written page's data, unpacked and indexed as a browser would: node page.js PAGE.html QUERY
// Prints {"projects": n, "items": n, "names": [the first hits' names]}.
const pagedata = require("./pagedata");
(async () => {
  const { projects } = await pagedata.read(process.argv[2]);
  const ix = pagedata.index(projects);
  const res = ix.search(process.argv[3]);
  console.log(JSON.stringify({ projects: projects.length, items: ix.items.length,
                               names: res.hits.slice(0, 5).map((h) => ix.items[h.doc].n) }));
})();
