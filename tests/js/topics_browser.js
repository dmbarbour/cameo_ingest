// Topics across models in a real browser (plan SB CP4): node topics_browser.js CHROME PROFILE_DIR PAGE.html QUERY
// Opens the page with no search: browses the topics, opens one, then a subject of it; then searches,
// grouped by topic. Prints what it saw as JSON.
const path = require("path");
const chrome = require("./chrome");
const [chromeBin, profile, pagePath, query] = process.argv.slice(2);

(async () => {
  const c = await chrome.open(chromeBin, profile, "file://" + path.resolve(pagePath));
  const timer = setTimeout(() => { console.log(JSON.stringify({ error: "timed out", errors: c.errors })); c.close(); process.exit(1); }, 60000);
  const out = {};
  out.lead = await c.run("return (await wait(() => document.querySelector('#results .browse-lead'))).textContent;");
  out.topics = await c.run("return document.querySelectorAll('#results .group.topic').length;");
  out.subjects = await c.run(`document.querySelector('#results .group.topic .group-head').click();
    return await wait(() => document.querySelectorAll('.topic-body .group').length);`);
  out.models = await c.run("return document.querySelector('.topic-body .group-model').textContent;");
  out.diagrams = await c.run(`document.querySelector('.topic-body .group-head').click();
    return await wait(() => document.querySelectorAll('.topic-body .result').length);`);
  out.byModel = await c.run(`[...document.querySelectorAll('.browse-lead a')].find((a) => /model/.test(a.textContent)).click();
    return await wait(() => document.querySelectorAll('#results > .result').length);`);
  out.grouping = await c.run("return document.getElementById('grouped').value;");
  out.count = await c.run(`const q = document.getElementById('q'); q.value = ${JSON.stringify(query)};
    q.dispatchEvent(new Event('input'));
    return await wait(() => / in \\d+ topics?$/.test(document.getElementById('count').textContent) && document.getElementById('count').textContent);`);
  out.spans = await c.run("return [...document.querySelectorAll('#results .group-model')].map((m) => m.textContent);");
  out.errors = c.errors;
  clearTimeout(timer);
  console.log(JSON.stringify(out));
  c.close();
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ error: String(e) })); process.exit(1); });
