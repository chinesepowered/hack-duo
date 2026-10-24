// Insert for the plan scene: open the plan turn's agent steps in TrueForge and show the sandbox
// (Code Mode) script, then splice it onto the end of s04b_plan with the Capy panel frozen on its last frame.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const OUT = path.join(__dirname, 'out', 'clips');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ff = (...a) => execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...a]);
const TF = 'http://localhost:8790/api/v1';

async function codeModeIntent(sid) {  // last exec in the plan turn whose script imports the MCP client
  const turns = (await (await fetch(`${TF}/sessions/${sid}/turns?page_size=50`)).json()).data;
  const plan = turns.find((t) => JSON.stringify(t.input || '').includes('Plan my'));
  if (!plan) return null;
  const events = (await (await fetch(`${TF}/sessions/${sid}/turns/${plan.id}/events?page_size=100`)).json()).data;
  const execs = events.flatMap((e) => e.tool_calls || []).filter((c) => c.function.name === 'exec')
    .map((c) => JSON.parse(c.function.arguments)).filter((a) => /mcp_client|call_tool\(/.test(a.command || ''));
  return execs.length ? execs[execs.length - 1].intent : null;
}

(async () => {
  const { sid1 } = JSON.parse(fs.readFileSync(path.join(OUT, 'state.json')));
  const tmp = fs.mkdtempSync(path.join(OUT, 'insert-'));
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 960, height: 900 }, timezoneId: 'America/Los_Angeles',
                                   recordVideo: { dir: tmp, size: { width: 960, height: 900 } } });
  const p = await ctx.newPage();
  await p.goto(`http://localhost:8790/sessions/${sid1}`, { waitUntil: 'networkidle' });
  await sleep(1500);
  // the plan turn's "Agent steps": the first toggle after the "Plan my …" message
  const idx = await p.evaluate(() => {
    const leaf = (re) => [...document.querySelectorAll('*')].filter((e) => e.childElementCount === 0 && re.test(e.textContent.trim()));
    const ask = leaf(/^Plan my/)[0];
    return leaf(/^Agent steps$/).findIndex((e) => ask && (ask.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING));
  });
  if (idx < 0) throw new Error('plan turn not found');
  const toggle = p.getByText(/^Agent steps$/).nth(idx);
  await toggle.scrollIntoViewIfNeeded();
  await sleep(1200);
  await toggle.click();
  await sleep(1500);
  // the sandbox step whose script calls the graph tools (Code Mode); its row title is the exec "intent"
  const intent = await codeModeIntent(sid1);
  const rows = p.locator('span.truncate.font-medium');
  const run = intent ? rows.filter({ hasText: intent.slice(0, 48) }).first()
                     : rows.filter({ hasNotText: /^(Listing tools|get_tool_info|call_tool|get_current_datetime)/ }).last();
  await run.scrollIntoViewIfNeeded();
  await run.click();
  await sleep(1200);
  // bring the script into view: its COMMAND block at the top of the chat
  await p.evaluate(() => {
    const cmd = [...document.querySelectorAll('*')].filter((e) => e.childElementCount === 0 && /^command$/i.test(e.textContent.trim())).pop();
    if (cmd) cmd.scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
  await sleep(5500);
  const v = p.video();
  await ctx.close(); await b.close();
  const left = path.join(OUT, 's04c_code_L.webm');
  fs.renameSync(await v.path(), left);
  fs.rmSync(tmp, { recursive: true, force: true });

  // right half: freeze the Capy panel's last frame from the plan scene
  const still = path.join(OUT, 's04b_plan_R_last.png');
  ff('-sseof', '-0.3', '-i', path.join(OUT, 's04b_plan_R.webm'), '-frames:v', '1', still);
  const insert = path.join(OUT, 's04c_code.mp4');
  ff('-i', left, '-loop', '1', '-i', still, '-filter_complex',
     '[1:v]scale=640:900,setsar=1[r];[0:v][r]hstack=inputs=2:shortest=1,fps=30,format=yuv420p[v]',
     '-map', '[v]', '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast', insert);
  // splice: plan scene (raw kept) + insert
  const raw = path.join(OUT, 's04b_plan_raw.mp4');
  if (!fs.existsSync(raw)) fs.copyFileSync(path.join(OUT, 's04b_plan.mp4'), raw);
  const list = path.join(OUT, 'plan_concat.txt');
  fs.writeFileSync(list, `file '${raw}'\nfile '${insert}'\n`);
  ff('-f', 'concat', '-safe', '0', '-i', list, '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
     path.join(OUT, 's04b_plan.mp4'));
  console.log('spliced code insert into s04b_plan.mp4');
})().catch((e) => { console.error(e); process.exit(1); });
