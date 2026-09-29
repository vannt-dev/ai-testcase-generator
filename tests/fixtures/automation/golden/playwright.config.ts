import { existsSync } from 'node:fs';
import { defineConfig, devices } from '@playwright/test';

// Values such as BASE_URL and passwords come from .env (see .env.example).
if (existsSync('.env')) process.loadEnvFile('.env');

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: 'html',
  use: {
    baseURL: process.env.BASE_URL ?? "https://staging.example.com",
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
