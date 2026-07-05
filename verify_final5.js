const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  
  await page.goto('https://fushanua.github.io/PBA/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  // Wait for images to load
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(5000);

  const imgData = await page.evaluate(() => {
    const imgs = document.querySelectorAll('.card .thumb img');
    return Array.from(imgs).slice(0, 30).map(img => ({
      src: img.src.substring(0, 70),
      naturalWidth: img.naturalWidth,
      complete: img.complete
    }));
  });
  
  const broken = imgData.filter(d => d.naturalWidth === 0);
  const ok = imgData.filter(d => d.naturalWidth > 0);
  console.log(`Checked: ${imgData.length}, OK: ${ok.length}, broken: ${broken.length}`);
  if (broken.length > 0) {
    broken.slice(0, 3).forEach(d => console.log(`  BROKEN: ${d.src} complete=${d.complete}`));
  }
  if (ok.length > 0) {
    ok.slice(0, 3).forEach(d => console.log(`  OK: ${d.src} (${d.naturalWidth}px)`));
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

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
