import { type Locator, type Page } from '@playwright/test';

export class LoginPage {
  readonly path = "/login";
  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly submitButton: Locator;
  readonly rememberMe: Locator;
  readonly errorBanner: Locator;

  constructor(readonly page: Page) {
    this.emailInput = page.getByLabel("Email");
    this.passwordInput = page.getByPlaceholder("Password");
    // TODO verify locator: not confirmed by an HTML/ARIA snapshot
    this.submitButton = page.getByRole("button", { name: "Sign in" });
    this.rememberMe = page.getByRole("checkbox", { name: "Remember me" });
    this.errorBanner = page.getByTestId("login-error");
  }

  async goto() {
    await this.page.goto(this.path);
  }
}
