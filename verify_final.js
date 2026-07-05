const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  
  // Track failed image requests
  const failedImgs = [];
  page.on('response', resp => {
    if (resp.url().includes('/images/') && resp.status() >= 400) {
      failedImgs.push({ url: resp.url().substring(0, 80), status: resp.status() });
    }
  });

  await page.goto('https://fushanua.github.io/PBA/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(5000);

  const imgData = await page.evaluate(() => {
    const imgs = document.querySelectorAll('.card .thumb img');
    return Array.from(imgs).slice(0, 30).map(img => ({
      src: img.src.substring(0, 80),
      naturalWidth: img.naturalWidth,
      ok: img.naturalWidth > 0
    }));
  });
  
  const broken = imgData.filter(d => !d.ok);
  console.log(`Cards checked: ${imgData.length}, broken: ${broken.length}`);
  if (broken.length > 0) {
    console.log('Broken examples:');
    broken.slice(0, 5).forEach(d => console.log(`  ${d.src}`));
  }

  // Check dates
  const cards = await page.locator('.card').all();
  let wsCards = 0, withDate = 0;
  for (const card of cards.slice(0, 30)) {
    const meta = await card.locator('.meta').textContent().catch(() => '');
    const badge = await card.locator('.source-badge').textContent().catch(() => '');
    if (badge && badge.includes('Website')) {
      wsCards++;
      if (meta && !meta.includes('归档') && /\d{4}/.test(meta)) withDate++;
    }
  }
  console.log(`Website cards: ${wsCards}, with real date: ${withDate}`);

  console.log(`Failed image responses: ${failedImgs.length}`);

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
