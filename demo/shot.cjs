// usage: node shot.cjs <url> <out.png> [waitMs]
const { chromium } = require('playwright');
(async () => {
  const [url, out, wait] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  p.on('console', m => { if (m.type() === 'error') console.log('console error:', m.text().slice(0, 200)); });
  p.on('pageerror', e => console.log('page error:', String(e).slice(0, 200)));
  await p.goto(url, { waitUntil: 'networkidle' });
  await p.waitForTimeout(Number(wait || 3500));
  await p.screenshot({ path: out });
  await b.close();
})();
