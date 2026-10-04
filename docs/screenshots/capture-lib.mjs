import { chromium } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { statSync, unlinkSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
// Public production pages, fresh signed-out browser; no response mocking.
export async function capture({ url, shots }) {
  execFileSync('cwebp', ['-version'], { stdio: 'ignore' });
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce', colorScheme: 'light', locale: 'en-US' });
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    if (!response?.ok()) throw new Error(`Page returned ${response?.status()}: ${url}`);
    const shoot = async name => {
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(1500);
      await page.waitForFunction(() => [...document.images].filter(img => {
        const r = img.getBoundingClientRect();
        return img.currentSrc && img.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && r.width && r.height && r.top < innerHeight && r.bottom > 0;
      }).every(img => img.complete && img.naturalWidth > 0));
      const png = path.join(here, `${name}.png`), out = path.join(here, `${name}.webp`);
      await page.screenshot({ path: png, animations: 'disabled' });
      for (const quality of [82, 72, 62, 50, 40]) {
        execFileSync('cwebp', ['-quiet', '-q', String(quality), png, '-o', out]);
        if (statSync(out).size < 300000) { unlinkSync(png); console.log(`${name}: ${page.url()}`); return; }
      }
      throw new Error(`${name} exceeds 300 KB`);
    };
    await shots(page, shoot);
  } finally { await browser.close(); }
}
