// Record each demo scene as real screen video of the running apps (no mockups).
//   card scenes: the title cards page, for exactly the narration length
//   app scenes:  TrueForge chat (left, 960px) + Capy panel (right, 640px), driven like a user would
// usage: node demo/record.cjs [scene ...]     (default: all)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const OUT = path.join(__dirname, 'out', 'clips');
const AUDIO = path.join(__dirname, 'out', 'audio');
const TF = 'http://localhost:8790';
const CAPY = 'http://127.0.0.1:8001';
const H = 900, LEFT = 960, RIGHT = 640;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const dur = (f) => parseFloat(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).toString());
const state = path.join(OUT, 'state.json');
const load = () => (fs.existsSync(state) ? JSON.parse(fs.readFileSync(state)) : {});
const save = (s) => fs.writeFileSync(state, JSON.stringify(s, null, 1));

async function api(method, p, body) {
  const r = await fetch(TF + p, { method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  return r.json();
}
const newSession = async () => (await api('POST', '/api/v1/sessions', { agent: { name: 'capy' } })).data.id;
const turns = async (sid) => (await api('GET', `/api/v1/sessions/${sid}/turns`)).data || [];

async function waitTurn(sid, beforeIds, timeout = 240000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    const ts = await turns(sid);
    const fresh = ts.find((t) => !beforeIds.has(t.id));
    if (fresh && !['running', 'queued', 'pending'].includes(fresh.state.status)) return fresh.state.status;
    await sleep(1500);
  }
  throw new Error('turn timeout');
}

async function ask(L, sid, text) {
  const before = new Set((await turns(sid)).map((t) => t.id));
  const box = L.getByPlaceholder(/Ask anything/).last();
  await box.click();
  await box.pressSequentially(text, { delay: 28 });
  await sleep(400);
  await L.keyboard.press('Enter');
  const status = await waitTurn(sid, before);
  await sleep(2500);
  return status;
}

async function approve(L, sid) {
  const before = new Set((await turns(sid)).map((t) => t.id));
  const btn = L.getByRole('button', { name: /^(Allow|Approve)$/i }).last();
  await btn.waitFor({ timeout: 20000 });
  await btn.scrollIntoViewIfNeeded();
  await sleep(1800);
  await btn.click();
  const status = await waitTurn(sid, before);
  await sleep(3000);
  return status;
}

async function withPages(name, fn) {
  const tmp = fs.mkdtempSync(path.join(OUT, `${name}-`));
  const browser = await chromium.launch();
  const mk = (w, sub) => browser.newContext({ viewport: { width: w, height: H }, deviceScaleFactor: 1, timezoneId: 'America/Los_Angeles',
                                              recordVideo: { dir: path.join(tmp, sub), size: { width: w, height: H } } });
  const [cL, cR] = await Promise.all([mk(LEFT, 'L'), mk(RIGHT, 'R')]);
  const [L, R] = await Promise.all([cL.newPage(), cR.newPage()]);
  try {
    await fn(L, R);
  } finally {
    const [vL, vR] = [L.video(), R.video()];
    await Promise.all([cL.close(), cR.close()]);
    await browser.close();
    fs.renameSync(await vL.path(), path.join(OUT, `${name}_L.webm`));
    fs.renameSync(await vR.path(), path.join(OUT, `${name}_R.webm`));
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', path.join(OUT, `${name}_L.webm`), '-i', path.join(OUT, `${name}_R.webm`),
    '-filter_complex', '[0:v][1:v]hstack=inputs=2,fps=30,format=yuv420p[v]', '-map', '[v]', '-c:v', 'libx264', '-crf', '20',
    '-preset', 'veryfast', path.join(OUT, `${name}.mp4`)]);
  console.log(`recorded ${name}.mp4 (${dur(path.join(OUT, `${name}.mp4`)).toFixed(1)}s)`);
}

async function card(scene) {
  const tmp = fs.mkdtempSync(path.join(OUT, `${scene}-`));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1,
                                         recordVideo: { dir: tmp, size: { width: 1600, height: 900 } } });
  const page = await ctx.newPage();
  await page.goto(`${CAPY}/assets/cards.html?scene=${scene}`, { waitUntil: 'networkidle' });
  await sleep((dur(path.join(AUDIO, `${scene}.mp3`)) + 1.2) * 1000);
  const v = page.video();
  await ctx.close(); await browser.close();
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', await v.path(), '-vf', 'fps=30,format=yuv420p', '-c:v', 'libx264',
    '-crf', '20', '-preset', 'veryfast', path.join(OUT, `${scene}.mp4`)]);
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(`recorded ${scene}.mp4`);
}

function sandbox(mode) {  // Code Mode needs the Daytona sandbox; keep it off otherwise to save credits
  execFileSync(path.join(__dirname, '..', '.venv', 'bin', 'python'), ['-m', 'scripts.setup_trueforge', '--only', 'agents'],
               { cwd: path.join(__dirname, '..'), env: { ...process.env, CAPY_SANDBOX: mode, CAPY_SKILL: 'off' }, stdio: 'ignore' });
}

const SCENES = {
  s01_title: () => card('s01_title'),
  s02_problem: () => card('s02_problem'),
  s05_data: () => card('s05_data'),
  s09_hood: () => card('s09_hood'),
  s10_outro: () => card('s10_outro'),
  // ask + lit path (narrations s03 + s04 play over this one clip)
  s03_ask: () => withPages('s03_ask', async (L, R) => {
    const st = load(); st.sid1 = await newSession(); save(st);
    await Promise.all([R.goto(`${CAPY}/?side`), L.goto(`${TF}/sessions/${st.sid1}`)]);
    await sleep(2500);
    await ask(L, st.sid1, "Hi Capy! Code review can't keep up with all the AI-generated pull requests on my team. Who here already solved that?");
    await sleep(6000);
  }),
  s04b_plan: () => withPages('s04b_plan', async (L, R) => {
    const st = load();
    sandbox('on');
    try {
      await Promise.all([R.goto(`${CAPY}/?side`), L.goto(`${TF}/sessions/${st.sid1}`)]);
      await sleep(2500);
      await ask(L, st.sid1, 'Plan my Wednesday so I can catch Franck, David and Sameen. Use the sandbox to pull their sessions, sort by time and flag any clashes.');
      await sleep(6000);
    } finally { sandbox('off'); }
  }),
  s06_lookup: () => withPages('s06_lookup', async (L, R) => {
    const st = load();
    await Promise.all([R.goto(`${CAPY}/?side`), L.goto(`${TF}/sessions/${st.sid1}`)]);
    await sleep(2500);
    await ask(L, st.sid1, process.env.LOOKUP_PROMPT || 'I just bumped into Andy Kelly from Precisely at the badge party! Look him up fresh. What do we have in common?');
    await sleep(5000);
  }),
  s07_memory: () => withPages('s07_memory', async (L, R) => {
    const st = load();
    await Promise.all([R.goto(`${CAPY}/?side`), L.goto(`${TF}/sessions/${st.sid1}`)]);
    await sleep(2000);
    await ask(L, st.sid1, 'Remember that I met Franck Nijhof after his Home Assistant session. We swapped notes on PR review load, and I promised to send him our numbers: agent PRs tripled since June, and our median review wait is 2.5 days.');
    await sleep(2500);
    st.sid2 = await newSession(); save(st);
    await L.goto(`${TF}/sessions/${st.sid2}`);
    await sleep(2000);
    await ask(L, st.sid2, 'Good morning Capy! ☕ Who am I waiting to follow up with?');
    await sleep(4000);
  }),
  s08_approve: () => withPages('s08_approve', async (L, R) => {
    const st = load();
    await Promise.all([R.goto(`${CAPY}/?side`), L.goto(`${TF}/sessions/${st.sid2}`)]);
    await sleep(2000);
    const status = await ask(L, st.sid2, 'Please draft a short follow-up to Franck and send it.');
    console.log('turn status before approval:', status);
    const gated = await L.getByRole('button', { name: /^(Allow|Approve)$/i }).last().isVisible().catch(() => false);
    if (!gated) {  // Capy showed the draft and asked first; say yes like a user would
      await sleep(2500);
      await ask(L, st.sid2, 'Looks great, send it.');
    }
    await approve(L, st.sid2);
    await sleep(3000);
  }),
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const which = process.argv.slice(2);
  for (const name of which.length ? which : Object.keys(SCENES)) {
    await SCENES[name]();
  }
})().catch((e) => { console.error(e); process.exit(1); });
