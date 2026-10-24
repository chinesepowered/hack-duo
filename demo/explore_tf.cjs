const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1000, height: 900 } });
  await p.goto('http://localhost:8790/', { waitUntil: 'networkidle' });
  await p.getByText('Hi Capy! Who should I meet', { exact: false }).first().click();
  await p.waitForTimeout(3000);
  console.log('URL:', p.url());
  await p.screenshot({ path: process.argv[2], fullPage: false });
  const html = await p.content();
  console.log('composer textareas:', (html.match(/<textarea/g) || []).length);
  await b.close();
})();
