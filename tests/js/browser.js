// The search page in a real browser: headless Chrome (chrome.js). Run from tests/test_searchpage.py:
//   node browser.js CHROME PROFILE_DIR PAGE.html DIAGRAM_DOC SHAPE_KEY QUERY
// Opens the page with a search, then the diagram, clicks the shape and the sketch, then clears the
// search and browses a model's subjects (plan SB-07c), and prints what it saw as JSON: the ready
// line, the search's count and first result, the sketch's linked shapes, the tooltip and heading
// after the click, whether the sketch zoomed, the models, views and subjects listed, the diagrams
// a subject opened, and any script errors. With SHOT=FILE.png, a screenshot of the browse pane.
const path = require("path");
const chrome = require("./chrome");
const [chromeBin, profile, pagePath, doc, key, query] = process.argv.slice(2);
const page = "file://" + path.resolve(pagePath);

chrome.walk(chromeBin, profile, `${page}#q=${encodeURIComponent(query)}`, async (c, out) => {
  out.ready = await c.run("return await wait(() => document.getElementById('ready').textContent);");
  out.search = await c.run("return await wait(() => document.getElementById('count').textContent);");
  out.first = await c.run("return await wait(() => (document.querySelector('.result-name') || {}).textContent);");
  await c.run(`location.hash = '#d${doc}'; return true;`);
  out.linked = await c.run("return await wait(() => document.querySelectorAll('.sketch svg .linked').length);");
  out.tags = await c.run("return document.querySelectorAll('#detail a.tag').length;");
  out.fullText = await c.run("return [...document.querySelectorAll('#detail h3')].map((h) => h.textContent);");
  out.tooltip = await c.run(`const g = document.querySelector('.sketch svg g.linked[data-k="${key}"]');
                               return g ? g.querySelector('title').textContent : null;`);
  out.heading = await c.run(`const before = document.querySelector('#detail h2').textContent;
    document.querySelector('.sketch svg g.linked[data-k="${key}"]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return await wait(() => { const h = document.querySelector('#detail h2').textContent; return h !== before && h; });`);
  out.hash = await c.run("return location.hash;");
  await c.run(`history.back(); return true;`);
  out.zoomed = await c.run(`const f = await wait(() => document.querySelector('.sketch'));
    await wait(() => f.querySelector('svg'));
    f.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return f.classList.contains('zoomed');`);
  await c.run(`history.replaceState(null, "", location.pathname); const q = document.getElementById('q');
    q.value = ''; q.dispatchEvent(new Event('input')); return true;`);
  out.models = await c.run(`await wait(() => document.querySelector('#results .browse-lead'));
    return document.querySelectorAll('#results .result').length;`);
  out.views = await c.run(`const rows = [...document.querySelectorAll('#results .result')];
    (rows.find((r) => /[2-9] views/.test(r.textContent)) || rows[0]).click();
    return await wait(() => document.querySelectorAll('.browse-head option').length);`);
  out.subjects = await c.run("return document.querySelectorAll('#results .group').length;");
  out.opened = await c.run(`document.querySelector('#results .group-head').click();
    return await wait(() => document.querySelectorAll('#results .group .result').length);`);
  out.chooserClosed = await c.run("return getComputedStyle(document.getElementById('chooser')).display === 'none';");
  out.chooser = await c.run(`document.getElementById('models').click();
    await wait(() => getComputedStyle(document.getElementById('chooser')).display !== 'none');
    return [...document.querySelectorAll('#mlist .mrow')].filter((r) => r.offsetParent !== null).length;`);
  out.button = await c.run("return document.getElementById('models').textContent;");
  out.compareDisabled = await c.run("return document.getElementById('mcompare').disabled;");  // one model: none to compare
  if (process.env.SHOT) {
    const shot = await c.send("Page.captureScreenshot", { format: "png" });
    require("fs").writeFileSync(process.env.SHOT, Buffer.from(shot.result.data, "base64"));
  }
});
