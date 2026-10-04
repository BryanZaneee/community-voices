import { createHash } from 'node:crypto';
import { capture } from './capture-lib.mjs';

// Reviewed October 4, 2026. Pin both week and text; never adopt a new report silently.
const reviewedTextHash = 'ee30a45f2b14ae17cc6a50230bd0e8c3b9ad878a72f5e37794b51a5e6fc29480';
await capture({
  url: 'https://bryanzane.com/community-voices/',
  async shots(page, shoot) {
    await page.setViewportSize({ width: 1440, height: 580 });
    await page.getByLabel('Week of').selectOption('2026-07-14');
    await page.getByText('Memory Crisis, EA Ads, and a Two-Year Screenshot Milestone', { exact: true }).waitFor();
    const text = (await page.locator('main').innerText()).replace(/\s+/g, ' ').trim();
    if (createHash('sha256').update(text).digest('hex') !== reviewedTextHash) {
      throw new Error('Report content changed. Review the live text and final image before updating reviewedTextHash; keep the existing README screenshot until then.');
    }
    // Frame the overview and first topic, excluding lower discussion cards.
    await shoot('report');
  }
});
