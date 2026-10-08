// Headless Chrome, driven over the DevTools protocol on --remote-debugging-pipe (no library
// needed), for the browser tests: `open(CHROME, PROFILE_DIR, URL)` gives {run, send, errors, close};
// `walk` wraps a test's steps.
// `run(body)` runs an async function's body in the page and returns its value; `wait(f, ms)` is
// in scope there, polling until f() is truthy.
const { spawn } = require("child_process");

async function open(chromeBin, profile, url) {
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
  let session;
  function send(method, params, sessionId = session) {
    const msg = { id: ++id, method, params: params || {} };
    if (sessionId) msg.sessionId = sessionId;
    toChrome.write(JSON.stringify(msg) + "\0");
    return new Promise((r) => waiting.set(msg.id, r));
  }
  async function run(body) {
    const helpers = "const wait = async (f, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) " +
      "{ const v = f(); if (v) return v; await new Promise((r) => setTimeout(r, 50)); } return null; };";
    const r = await send("Runtime.evaluate", { expression: `(async () => { ${helpers} ${body} })()`,
                                               awaitPromise: true, returnByValue: true });
    if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
    return r.result.result.value;
  }
  const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" }, null);
  session = (await send("Target.attachToTarget", { targetId, flatten: true }, null)).result.sessionId;
  await send("Runtime.enable", {});
  await send("Page.navigate", { url });
  return { run, send, errors, close: () => chrome.kill() };
}

// Opens `url`, runs `steps(c, out)`, then prints `out` with the page's script errors as JSON and
// exits; a step that throws, or a minute's wait, prints {error, errors} and exits with 1.
async function walk(chromeBin, profile, url, steps) {
  let c = null;
  const fail = (error) => {
    console.log(JSON.stringify({ error, errors: c ? c.errors : [] }));
    if (c) c.close();
    process.exit(1);
  };
  const timer = setTimeout(() => fail("timed out"), 60000);
  try {
    c = await open(chromeBin, profile, url);
    const out = {};
    await steps(c, out);
    out.errors = c.errors;
    clearTimeout(timer);
    console.log(JSON.stringify(out));
    c.close();
    process.exit(0);
  } catch (e) {
    fail(String(e));
  }
}

module.exports = { open, walk };
