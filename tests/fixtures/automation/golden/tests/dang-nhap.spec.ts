import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/LoginPage';
import { TrangChu } from '../pages/TrangChu';

test("TC_LOGIN_001 Login with valid credentials", async ({ page }) => {
  const loginPage = new LoginPage(page);
  const trangChu = new TrangChu(page);
  // Open the login page
  await loginPage.goto();
  // Enter a valid email
  await loginPage.emailInput.fill("user@example.com");
  // Enter the password
  await loginPage.passwordInput.fill(process.env.TEST_PASSWORD ?? '');
  // Tick * / Remember me
  await loginPage.rememberMe.check();
  // Press Enter
  await loginPage.passwordInput.press("Enter");
  // The home page opens
  await expect(page).toHaveURL(new RegExp("\\/home\\?tab=1"));
  // Search is shown
  await expect(trangChu.searchBox).toBeVisible();
  // Line one line two
  await expect(trangChu.welcomeText).toContainText("Welcome back");
});

test("TC_LOGIN_002 Wrong password shows an error", async ({ page }) => {
  const loginPage = new LoginPage(page);
  const trangChu = new TrangChu(page);
  // Open the login page
  await loginPage.goto();
  // Enter a valid email
  await loginPage.emailInput.fill("user@example.com");
  // Enter a wrong password
  await loginPage.passwordInput.fill("wrong`${x}'pass\"");
  // Click Sign in
  await loginPage.submitButton.click();
  // An error is shown
  await expect(loginPage.errorBanner).toBeVisible();
  // The account menu is not shown
  await expect(trangChu.userMenu).toBeHidden();
});
