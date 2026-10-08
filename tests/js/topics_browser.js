// Topics across models in a real browser (plan SB CP4): node topics_browser.js CHROME PROFILE_DIR PAGE.html QUERY
// Opens the page with no search: browses the topics, opens one, then a subject of it; then searches,
// grouped by topic. Prints what it saw as JSON.
const path = require("path");
const chrome = require("./chrome");
const [chromeBin, profile, pagePath, query] = process.argv.slice(2);

chrome.walk(chromeBin, profile, "file://" + path.resolve(pagePath), async (c, out) => {
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
  // cleared, the search leaves nothing behind: an item opened from browsing marks no words (CQ-002)
  const openFirst = `const q = document.getElementById('q'); q.value = ''; q.dispatchEvent(new Event('input'));
    await wait(() => document.querySelector('#results .browse-lead'));
    const back = [...document.querySelectorAll('.browse-lead a')].find((a) => /topics/.test(a.textContent));
    if (back) back.click(); // browsing may have been switched to models
    await wait(() => document.querySelector('#results .group.topic'));
    if (!document.querySelector('.topic-body .group-head')) document.querySelector('#results .group.topic .group-head').click();
    if (!document.querySelector('.topic-body .result')) (await wait(() => document.querySelector('.topic-body .group-head'))).click();
    (await wait(() => document.querySelector('.topic-body .result'))).click();
    return (await wait(() => document.querySelector('#detail h2'))).textContent;`;
  const name = await c.run(openFirst);
  const word = (name.match(/[A-Za-z]{4,}/) || [name])[0];
  out.marksBefore = await c.run(`const q = document.getElementById('q'); q.value = ${JSON.stringify(word)}; q.dispatchEvent(new Event('input'));
    await wait(() => /found/.test(document.getElementById('count').textContent));
    document.querySelector('#results .result').click();
    await wait(() => document.querySelector('#detail mark'));
    return document.querySelectorAll('#detail mark').length;`);
  await c.run(openFirst);
  out.marksAfterClear = await c.run("return document.querySelectorAll('#detail mark').length;");
});
