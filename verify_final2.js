const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, bypassCSP: true });

  const responses = [];
  page.on('response', resp => {
    if (resp.url().includes('/images/') && resp.url().includes('.jpg') || resp.url().includes('.png')) {
      responses.push({ url: resp.url().substring(0, 80), status: resp.status(), type: resp.headers()['content-type'] });
    }
  });

  await page.goto('https://fushanua.github.io/PBA/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(8000);

  // Get detailed image data
  const imgData = await page.evaluate(() => {
    const imgs = document.querySelectorAll('.card .thumb img');
    return Array.from(imgs).slice(0, 10).map(img => ({
      src: img.src,
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      complete: img.complete,
      currentSrc: img.currentSrc
    }));
  });

  console.log('Image details:');
  imgData.forEach((d, i) => {
    console.log(`  [${i}] ${d.naturalWidth}x${d.naturalHeight} complete=${d.complete} src=${d.src.substring(0, 70)}`);
  });

  console.log(`\nImage responses: ${responses.length}`);
  responses.slice(0, 10).forEach(r => console.log(`  ${r.status} ${r.type} ${r.url}`));

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
