// The model chooser's groups and notes (plan LN-07): node chooser.js, prints "ok".
const assert = require("assert");
const Engine = require("../../src/cameo_ingest/assets/search.js");

const projects = [
  { label: "Tender [aaaa]", token: "t:tender", sv: "2025-02-10", sources: [{ path: "/x/bids/tender/R.mdzip" }] },
  { label: "Halvorsen v2 [bbbb]", token: "t:h2", sv: "2025-07-20", fm: "t:h2", rk: 0, nv: 2,
    kn: [["t:tender", "derived"], ["t:aquila", "root"]], sources: [{ path: "/x/bids/halvorsen/v2/R.mdzip" }] },
  { label: "Halvorsen [cccc]", token: "t:h1", sv: "2025-05-01", fm: "t:h2", rk: 1, nv: 2,
    kn: [["t:tender", "derived"]], sources: [{ path: "/x/bids/halvorsen/R.mdzip" }] },
  { label: "Aquila [dddd]", token: "t:aquila", sv: "2025-05-01", kn: [["t:tender", "derived"], ["t:h2", "root"]],
    sources: [{ path: "/x/bids/aquila/R.mdzip" }] },
  { label: "Kiosk [eeee]", token: "t:kiosk", sv: "2024-01-01", rl: ["t:aquila"], sources: [{ path: "/x/other/K.mdzip" }] },
];
const labelOf = (t) => projects.find((p) => p.token === t).label;

const lineage = Engine.chooserGroups(projects, "lineage");
assert.strictEqual(lineage.length, 2); // the tender and its bids together; the kiosk alone
const bids = lineage.find((g) => g.pids.includes(0));
assert.match(bids.title, /4 models built on one another/);
assert.deepStrictEqual(bids.pids.slice(0, 1), [0]); // the oldest family first: the tender
assert.ok(bids.pids.indexOf(1) < bids.pids.indexOf(2) && bids.depth.get(2) === 1); // newest, then its older version, indented
assert.strictEqual(lineage.find((g) => g.pids.includes(4)).title, null);

const folders = Engine.chooserGroups(projects, "folder");
assert.deepStrictEqual(folders.map((g) => g.title), ["bids/aquila", "bids/halvorsen", "bids/halvorsen/v2", "bids/tender", "other"]);
assert.deepStrictEqual(Engine.chooserGroups(projects, "date")[0].pids.slice(0, 2), [1, 3]); // newest saved first, ties by name
assert.deepStrictEqual(Engine.chooserGroups(projects, "name")[0].pids[0], 3); // Aquila

assert.strictEqual(Engine.lineageNote(projects[1], labelOf),
  "newest of 2 versions; derived by others from Tender [aaaa]; shares a root with Aquila [dddd]");
assert.strictEqual(Engine.lineageNote(projects[2], labelOf), "older version, 1 of 2; derived by others from Tender [aaaa]");
assert.strictEqual(Engine.lineageNote(projects[4], labelOf), "shares a part with Aquila [dddd]");
console.log("ok");
