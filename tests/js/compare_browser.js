// "Also in" and Compare in a real browser (plan SH): node compare_browser.js CHROME PROFILE_DIR PAGE.html QUERY LABEL
// Searches QUERY and opens the first result: its "Also in" section, the links and what each says.
// Then, in the model chooser, picks the first two models whose labels hold LABEL and compares them.
const path = require("path");
const chrome = require("./chrome");
const [chromeBin, profile, pagePath, query, label] = process.argv.slice(2);
const page = "file://" + path.resolve(pagePath);

chrome.walk(chromeBin, profile, `${page}#q=${encodeURIComponent(query)}`, async (c, out) => {
  out.first = await c.run(`(await wait(() => document.querySelector('#results .result'))).click();
    return (await wait(() => document.querySelector('#detail h2'))).textContent;`);
  out.sections = await c.run("return [...document.querySelectorAll('#detail h3')].map((h) => h.textContent);");
  out.also = await c.run(`const s = [...document.querySelectorAll('#detail .detail-section')].find((x) => x.querySelector('h3').textContent === 'Also in');
    return s ? [...s.querySelectorAll('li')].map((li) => ({ text: li.textContent, linked: !!li.querySelector('a') })) : null;`);
  out.compare = await c.run(`document.getElementById('models').click();
    await wait(() => getComputedStyle(document.getElementById('chooser')).display !== 'none');
    document.getElementById('mnone').click();
    const rows = () => [...document.querySelectorAll('#mlist .mrow')].filter((r) => r.textContent.includes(${JSON.stringify(label)}));
    for (let k = 0; k < 2; k++) rows()[k].querySelector('input').click();  // the list is drawn again after each
    const picked = rows().filter((r) => r.querySelector('input').checked).length;
    const button = document.getElementById('mcompare');
    if (button.disabled) return { picked, disabled: true };
    button.click();
    const lead = await wait(() => [...document.querySelectorAll('#results .browse-lead')].find((p) => /changed/.test(p.textContent)));
    return { picked, head: document.querySelector('#results .browse-head').textContent,
             lead: lead && lead.textContent, groups: document.querySelectorAll('#results .group').length };`);
  out.opened = await c.run(`const head = document.querySelector('#results .group .group-head');
    if (!head) return 0;
    head.click();
    return await wait(() => document.querySelectorAll('#results .group .result').length);`);
});
