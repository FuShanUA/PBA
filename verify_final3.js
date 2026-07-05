const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  
  await page.goto('https://fushanua.github.io/PBA/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(8000);

  const imgData = await page.evaluate(() => {
    const imgs = document.querySelectorAll('.card .thumb img');
    return Array.from(imgs).slice(0, 10).map(img => ({
      src: img.src,
      naturalWidth: img.naturalWidth,
    }));
  });
  
  const broken = imgData.filter(d => d.naturalWidth === 0);
  console.log(`Checked: ${imgData.length}, broken: ${broken.length}`);
  if (broken.length > 0) {
    console.log('First broken:', broken[0].src.substring(0, 80));
  }

  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
