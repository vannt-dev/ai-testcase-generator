import { type Locator, type Page } from '@playwright/test';

export class TrangChu {
  readonly path = "/";
  readonly userMenu: Locator;
  readonly welcomeText: Locator;
  readonly languageSelect: Locator;
  readonly searchBox: Locator;

  constructor(readonly page: Page) {
    // TODO verify locator: not confirmed by an HTML/ARIA snapshot
    this.userMenu = page.getByText("Account");
    this.welcomeText = page.getByText("Welcome back, \"friend\"");
    // TODO verify locator: not confirmed by an HTML/ARIA snapshot
    this.languageSelect = page.locator("select#lang");
    this.searchBox = page.getByRole("searchbox");
  }

  async goto() {
    await this.page.goto(this.path);
  }
}
