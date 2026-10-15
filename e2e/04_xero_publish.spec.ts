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
    // the report the wizard spec posted: its history row opens the Daily Report,
    // whose URL carries the report id
    await page.goto(`/entity/${entityId}/petty-cash/reports?status=submitted`);
    await page.locator('.pc-row__link').first().click();
    await expect(page).toHaveURL(/\/entity\/[0-9a-f]{8}\/[^/]+\/petty-cash\/reports\/([0-9a-f-]{36})\/summary/);
    const reportId = page.url().match(/\/entity\/[0-9a-f]{8}\/[^/]+\/petty-cash\/reports\/([0-9a-f-]{36})\/summary/)![1];

    // the submitted page carries the Publish button
    await page.goto(`/entity/${entityId}/petty-cash/reports/${reportId}/submitted`);
    // a report that has never been to Xero gets the first Publish (Republish is a different button)
    const publish = page.locator('#publishButton');
    await expect(publish).toBeVisible();
    await publish.click();
    // publishing is external, so it asks first (Part 15.9h); a first publish is no warning
    await expect(page.locator('#publishReportModal')).toBeVisible();
    await page.locator('#confirmPublishButton').click();

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
    await page.goto(`/entity/${entityId}/petty-cash/reports/${reportId}/submitted`);
    await expect(page.locator('#republishButton')).toBeVisible();
  });
});
