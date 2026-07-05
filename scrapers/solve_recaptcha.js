// Auto-solve reCAPTCHA v2 by clicking the checkbox inside the iframe
const { chromium } = require('playwright');

async function solveRecaptcha(page) {
  // reCAPTCHA v2 renders in an iframe from google.com
  // The checkbox is inside: <div class="recaptcha-checkbox-checkmark">
  
  console.log('Looking for reCAPTCHA iframe...');
  
  // Find the reCAPTCHA iframe
  for (let attempt = 0; attempt < 30; attempt++) {
    const frames = page.frames();
    for (const frame of frames) {
      const url = frame.url();
      if (url.includes('recaptcha') && url.includes('anchor')) {
        console.log('Found reCAPTCHA anchor iframe');
        
        try {
          // Click the checkbox
          const checkbox = frame.locator('.recaptcha-checkbox-border, #recaptcha-anchor');
          if (await checkbox.isVisible({ timeout: 2000 })) {
            await checkbox.click();
            console.log('Clicked reCAPTCHA checkbox');
            
            // Wait to see if it's solved (checkmark appears) or challenge appears
            await page.waitForTimeout(3000);
            
            // Check if solved
            const ariaChecked = await frame.locator('#recaptcha-anchor').getAttribute('aria-checked');
            if (ariaChecked === 'true') {
              console.log('reCAPTCHA SOLVED (no challenge needed)');
              return true;
            }
            
            // If challenge appeared, try audio challenge
            console.log('Challenge may have appeared, trying audio...');
            
            // Find the challenge iframe
            const challengeFrames = page.frames().filter(f => f.url().includes('recaptcha') && f.url().includes('bframe'));
            for (const cf of challengeFrames) {
              console.log('Found challenge iframe: ' + cf.url().substring(0, 80));
              
              // Click "Audio challenge" button
              try {
                const audioBtn = cf.locator('#recaptcha-audio-button, .rc-button-goog, button[aria-label*="audio"], a[aria-label*="audio"]');
                if (await audioBtn.isVisible({ timeout: 2000 })) {
                  await audioBtn.click();
                  console.log('Clicked audio challenge button');
                  await page.waitForTimeout(2000);
                  
                  // Get the audio source
                  const audioSrc = await cf.locator('audio').getAttribute('src').catch(() => null);
                  if (audioSrc) {
                    console.log('Audio source: ' + audioSrc.substring(0, 100));
                    // Download and transcribe the audio
                    // ... (would need speech recognition)
                  }
                  
                  // Get the challenge text (sometimes shown as text)
                  const challengeText = await cf.locator('.rc-audiochallenge-instructions, .rc-audiochallenge-msg').textContent().catch(() => '');
                  console.log('Challenge text: ' + challengeText);
                }
              } catch(e) {
                console.log('Audio challenge error: ' + e.message.substring(0, 80));
              }
            }
            
            return false;
          }
        } catch(e) {
          // Try next frame
        }
      }
    }
    await page.waitForTimeout(1000);
  }
  
  console.log('reCAPTCHA iframe not found');
  return false;
}

module.exports = { solveRecaptcha };
