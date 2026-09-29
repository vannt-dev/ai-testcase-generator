import { test, expect } from '@playwright/test';
import { TrangChu } from '../pages/TrangChu';

test.fixme("TC_HOME_001 Change language", async ({ page }) => {
  const trangChu = new TrangChu(page);
  // Open the home page
  await trangChu.goto();
  // Choose Vietnamese
  await trangChu.languageSelect.selectOption("vi");
  // Vietnamese is selected
  await expect(trangChu.languageSelect).toHaveValue("vi");
  // TODO: Untick the newsletter
  // TODO: Verify the page is translated
});

test.fixme("TC_HOME_001_2 Duplicate id without steps", async ({ page }) => {
  // TODO: No automatable steps were returned for this test case.
});
