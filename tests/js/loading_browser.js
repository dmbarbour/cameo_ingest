// The loading panel in a real browser: node loading_browser.js CHROME PROFILE_DIR PAGE.html
// Once the page is ready, shows the loading panel again and fills its lines with a short, then a
// very long, model name and count, at a desktop's width and a phone's. Prints, for each width,
// the panel's line heights with each text, whether the page scrolls sideways, and whether the
// hidden search shows below the panel, as JSON: the
// bars must not move when a name is long (one line each).
const path = require("path");
const chrome = require("./chrome");
const [chromeBin, profile, pagePath] = process.argv.slice(2);

const measure = `
  await wait(() => (document.getElementById('ready') || {}).textContent);
  document.getElementById('app').hidden = true;
  document.getElementById('loading').hidden = false;
  const lines = () => [document.querySelector('.reading'), ...document.querySelectorAll('.phase')]
    .map((e) => e.getBoundingClientRect().height);
  const fill = (name, info) => {
    document.getElementById('reading').textContent = 'Unpacking ' + name + '…';
    for (const i of document.querySelectorAll('.phase-info')) i.textContent = info;
  };
  fill('Kois', '1 of 7, 0.1 s');
  const short = lines();
  const name = 'A model whose name runs on and on, as some file names do, until it is far wider than the panel.mdzip';
  fill(name, name + ' (1,234,567 of 9,876,543), 1234.5 s');
  const long = lines();
  const page = document.documentElement;
  return { short, long, sideways: page.scrollWidth > page.clientWidth,
           appShown: document.getElementById('app').getBoundingClientRect().height > 0 };`;

chrome.walk(chromeBin, profile, "file://" + path.resolve(pagePath), async (c, out) => {
  out.desktop = await c.run(measure);
  await c.send("Emulation.setDeviceMetricsOverride", { width: 360, height: 740, deviceScaleFactor: 1, mobile: true });
  out.phone = await c.run(measure);
});
