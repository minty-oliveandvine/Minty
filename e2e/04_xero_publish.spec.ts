// Publishing the submitted report to Xero, for real: the one contract no other test touches
// (scopes, the token refresh, the tenant, the Files API receipt upload). Runs only with
// E2E_XERO=1, against a shop linked to a Demo Company by hand; every run writes real bank
// transactions into that organisation, which is what a Demo Company is for.
//
// Relies on 02_report_wizard having posted yesterday's report in this run (the specs run in
// file order on one worker), and on the shop's mapping pointing at the organisation's real
// accounts and contacts (scripts/e2e_seed.py leaves a connected shop's mapping alone).
import { expect, test } from '@playwright/test';
import { login, requireCredentials, requireStack, xeroLive } from './helpers';

test.describe('publish to Xero', () => {
  test.skip(!xeroLive(), 'set E2E_XERO=1 against a shop connected to a Xero Demo Company');

  test('the submitted report publishes and the sync records it', async ({ page }) => {
    test.setTimeout(180_000); // Xero round-trips: the bank transactions, the transfer, the receipt
    await requireStack();
    const creds = requireCredentials();
    await login(page, creds);
    const entityId = creds.entityId;
    // the report the wizard spec posted: "View Report" on the history page opens its ending
    // summary, whose URL carries the report id
    await page.goto(`/entity/${entityId}/reports`);
    await page.getByRole('link', { name: /view report/i }).first().click();
    await expect(page).toHaveURL(/\/entity\/[0-9a-f]{8}\/[^/]+\/reports\/([0-9a-f-]{36})\/summary/);
    const reportId = page.url().match(/\/entity\/[0-9a-f]{8}\/[^/]+\/reports\/([0-9a-f-]{36})\/summary/)![1];

    // the submitted page carries the Publish button
    await page.goto(`/entity/${entityId}/reports/${reportId}/submitted`);
    // the button's accessible name starts with its logo's alt text; Republish is a different button
    const publish = page.getByRole('button', { name: /(^|\s)publish to xero$/i });
    await expect(publish).toBeVisible();
    await publish.click();
    // A report that has never been to Xero publishes straight away. Until the 2026-09-18 fix
    // of report_submitted() is deployed the page reads the NOT NULL 'unpublished' default as
    // "previously published" and asks for the duplicate-transactions confirmation first:
    // confirm it, and record that the deployment still shows it.
    const republishModal = page.locator('#republishReportModal');
    if (await republishModal.isVisible()) {
      test.info().annotations.push({
        type: 'defect', description: 'a never-published report got the republish warning (submitted.py fix not deployed yet)',
      });
      await page.locator('#confirmRepublishButton').click();
    }

    // the page polls /api/report/<id>/publishing_status until Xero has answered; do the same
    await expect
      .poll(
        async () => {
          const res = await page.request.get(`/api/report/${reportId}/publishing_status`);
          const body = await res.json();
          if (body.publishing_status === 'failed') {
            throw new Error(`publish failed: ${JSON.stringify(body.failure_reasons ?? body.failure_reason)}`);
          }
          return body.xero_integrated_yes === true ? 'published' : body.publishing_status;
        },
        { timeout: 150_000, intervals: [2_000, 3_000, 5_000] },
      )
      .toBe('published');

    // and the detail page says so
    await page.goto(`/entity/${entityId}/reports/${reportId}/submitted`);
    await expect(page.locator('#republishButton')).toBeVisible();
  });
});
