// A written page's data blocks, as the page reads them, for the node tests.
const fs = require("fs");
const Engine = require("../../src/cameo_ingest/assets/search.js");

const DATA = /<script type="application\/octet-stream" ([a-z-]+)="[^"]*"[^>]*>([^<]*)<\/script>/g;

// {projects: [decoded project blocks, in order], subjects, topics (decoded, or null)}.
async function read(pagePath) {
  const html = fs.readFileSync(pagePath, "utf8");
  const out = { projects: [], subjects: null, topics: null };
  for (const [, attr, b64] of html.matchAll(DATA)) {
    if (attr === "data-project") out.projects.push(await Engine.decode(b64));
    else if (attr === "data-subjects") out.subjects = await Engine.decode(b64);
    else if (attr === "data-topics") out.topics = await Engine.decode(b64);
  }
  return out;
}

// An index of the page's items, each with its project's page id, as the page builds it.
function index(projects) {
  const ix = new Engine.Index();
  projects.forEach((data, i) => { for (const it of data.items) { it.p = i; ix.add(it); } });
  ix.finish();
  return ix;
}

module.exports = { read, index };
