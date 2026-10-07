// The search page in a real browser: headless Chrome, driven over the DevTools protocol on
// --remote-debugging-pipe (no library needed). Run from tests/test_searchpage.py:
//   node browser.js CHROME PROFILE_DIR PAGE.html DIAGRAM_DOC SHAPE_KEY QUERY
// Opens the page with a search, then the diagram, clicks the shape and the sketch, then clears the
// search and browses a model's subjects (plan SB-07c), and prints what it saw as JSON: the ready
// line, the search's count and first result, the sketch's linked shapes, the tooltip and heading
// after the click, whether the sketch zoomed, the models, views and subjects listed, the diagrams
// a subject opened, and any script errors. With SHOT=FILE.png, a screenshot of the browse pane.
const { spawn } = require("child_process");
const path = require("path");
const [chromeBin, profile, pagePath, doc, key, query] = process.argv.slice(2);
const page = "file://" + path.resolve(pagePath);

const chrome = spawn(chromeBin, ["--headless=new", "--disable-gpu", "--no-sandbox", "--remote-debugging-pipe",
  `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"] });
const toChrome = chrome.stdio[3], fromChrome = chrome.stdio[4];
let id = 0, buf = "";
const waiting = new Map(), errors = [];
fromChrome.on("data", (d) => {
  buf += d.toString();
  let i;
  while ((i = buf.indexOf("\0")) >= 0) {
    const msg = JSON.parse(buf.slice(0, i));
    buf = buf.slice(i + 1);
    if (msg.method === "Runtime.exceptionThrown") errors.push(msg.params.exceptionDetails.text);
    if (msg.id && waiting.has(msg.id)) {
      waiting.get(msg.id)(msg);
      waiting.delete(msg.id);
    }
  }
});
function send(method, params, sessionId) {
  const msg = { id: ++id, method, params: params || {} };
  if (sessionId) msg.sessionId = sessionId;
  toChrome.write(JSON.stringify(msg) + "\0");
  return new Promise((r) => waiting.set(msg.id, r));
}
// Runs `body` (an async function's body) in the page and returns its value.
async function run(session, body) {
  const helpers = "const wait = async (f, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) " +
    "{ const v = f(); if (v) return v; await new Promise((r) => setTimeout(r, 50)); } return null; };";
  const r = await send("Runtime.evaluate", { expression: `(async () => { ${helpers} ${body} })()`,
                                             awaitPromise: true, returnByValue: true }, session);
  if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
  return r.result.result.value;
}

(async () => {
  const timer = setTimeout(() => { console.log(JSON.stringify({ error: "timed out", errors })); chrome.kill(); process.exit(1); }, 60000);
  const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
  const { result: { sessionId: s } } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Runtime.enable", {}, s);
  await send("Page.navigate", { url: `${page}#q=${encodeURIComponent(query)}` }, s);
  const out = {};
  out.ready = await run(s, "return await wait(() => document.getElementById('ready').textContent);");
  out.search = await run(s, "return await wait(() => document.getElementById('count').textContent);");
  out.first = await run(s, "return await wait(() => (document.querySelector('.result-name') || {}).textContent);");
  await run(s, `location.hash = '#d${doc}'; return true;`);
  out.linked = await run(s, "return await wait(() => document.querySelectorAll('.sketch svg .linked').length);");
  out.tags = await run(s, "return document.querySelectorAll('#detail a.tag').length;");
  out.fullText = await run(s, "return [...document.querySelectorAll('#detail h3')].map((h) => h.textContent);");
  out.tooltip = await run(s, `const g = document.querySelector('.sketch svg g.linked[data-k="${key}"]');
                               return g ? g.querySelector('title').textContent : null;`);
  out.heading = await run(s, `const before = document.querySelector('#detail h2').textContent;
    document.querySelector('.sketch svg g.linked[data-k="${key}"]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return await wait(() => { const h = document.querySelector('#detail h2').textContent; return h !== before && h; });`);
  out.hash = await run(s, "return location.hash;");
  await run(s, `history.back(); return true;`);
  out.zoomed = await run(s, `const f = await wait(() => document.querySelector('.sketch'));
    await wait(() => f.querySelector('svg'));
    f.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return f.classList.contains('zoomed');`);
  await run(s, `history.replaceState(null, "", location.pathname); const q = document.getElementById('q');
    q.value = ''; q.dispatchEvent(new Event('input')); return true;`);
  out.models = await run(s, `await wait(() => document.querySelector('#results .browse-lead'));
    return document.querySelectorAll('#results .result').length;`);
  out.views = await run(s, `const rows = [...document.querySelectorAll('#results .result')];
    (rows.find((r) => /[2-9] views/.test(r.textContent)) || rows[0]).click();
    return await wait(() => document.querySelectorAll('.browse-head option').length);`);
  out.subjects = await run(s, "return document.querySelectorAll('#results .group').length;");
  out.opened = await run(s, `document.querySelector('#results .group-head').click();
    return await wait(() => document.querySelectorAll('#results .group .result').length);`);
  out.chooserClosed = await run(s, "return getComputedStyle(document.getElementById('chooser')).display === 'none';");
  out.chooser = await run(s, `document.getElementById('models').click();
    await wait(() => getComputedStyle(document.getElementById('chooser')).display !== 'none');
    return [...document.querySelectorAll('#mlist .mrow')].filter((r) => r.offsetParent !== null).length;`);
  out.button = await run(s, "return document.getElementById('models').textContent;");
  out.compareDisabled = await run(s, "return document.getElementById('mcompare').disabled;");  // one model: none to compare
  if (process.env.SHOT) {
    const shot = await send("Page.captureScreenshot", { format: "png" }, s);
    require("fs").writeFileSync(process.env.SHOT, Buffer.from(shot.result.data, "base64"));
  }
  out.errors = errors;
  clearTimeout(timer);
  console.log(JSON.stringify(out));
  chrome.kill();
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ error: String(e), errors })); chrome.kill(); process.exit(1); });
