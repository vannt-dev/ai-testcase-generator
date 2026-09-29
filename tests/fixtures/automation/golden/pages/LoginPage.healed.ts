import { type Locator, type Page } from '@playwright/test';

export class LoginPage {
  readonly path = "/login";
  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly submitButton: Locator;
  readonly rememberMe: Locator;
  readonly errorBanner: Locator;

  constructor(readonly page: Page) {
    // healed: Label * / removed from the form
    // TODO verify locator: not confirmed by the new snapshot
    this.emailInput = page.getByTestId("login-email`${x}\"");
    this.passwordInput = page.getByPlaceholder("Password");
    // healed: Button text changed from 'Sign in' to 'Log in'
    this.submitButton = page.getByRole("button", { name: "Log in" });
    this.rememberMe = page.getByRole("checkbox", { name: "Remember me" });
    this.errorBanner = page.getByTestId("login-error");
  }

  async goto() {
    await this.page.goto(this.path);
  }
}
