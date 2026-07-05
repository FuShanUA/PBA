const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error' && msg.text().includes('image')) {
      errors.push(msg.text().substring(0, 120));
    }
  });
  page.on('requestfailed', req => {
    if (req.url().includes('/images/')) {
      errors.push(`FAILED: ${req.url().substring(0, 80)} - ${req.failure()?.errorText}`);
    }
  });

  await page.goto('https://fushanua.github.io/PBA/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(8000);

  // Try fetching an image directly via the page
  const result = await page.evaluate(async () => {
    try {
      const resp = await fetch('articles/images/0dccc1c2ca90.jpg');
      return { status: resp.status, type: resp.headers.get('content-type'), size: resp.headers.get('content-length') };
    } catch(e) {
      return { error: e.message };
    }
  });
  console.log('Direct fetch result:', JSON.stringify(result));

  console.log('Errors:', errors.length);
  errors.slice(0, 5).forEach(e => console.log(`  ${e}`));

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
