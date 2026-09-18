// Browser tests for Minty's own pages (the Jinja + inline-JS frontend). They run against a
// Flask that is ALREADY UP -- nothing is started here, for the same reason as onboarding/e2e:
// a service that failed to boot must read as "not reachable", not as a failed assertion.
//
//   npm run test:e2e
//
// docs/modernisation/modernisation_plan.md, Part 1 phase C0.9: this suite is the only thing that runs the
// wizard's JavaScript, which reads the field names and JSON keys the schema redesign renames.
// See e2e/README.md for the environment the authenticated specs need.

import { defineConfig, devices } from '@playwright/test';
import { BASE_URL } from './e2e/urls';

export default defineConfig({
  testDir: './e2e',
  // One worker: every spec signs in as the same seeded user and writes to one seeded entity.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
