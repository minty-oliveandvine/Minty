// The Daily Closing in a real browser (Part 15.9 / 15.15, redesigned 2026-10-14): Addition to
// Drawer -> Sales -> Expenses -> Cash Count (Bank Deposit folded in) -> Close -> the outcome page,
// then the posted day in history, its Daily Report and its movements CSV. This is the JavaScript
// the schema redesign can break silently (field names, JSON keys), so every step asserts what the
// page SHOWS, not what the database holds. Amounts are chosen so each total is a distinct number.
// The phone project runs the same journey at 360px (playwright.config.ts).
import { expect, test, type Page } from '@playwright/test';
import { RECEIPT_PDF, RECEIPT_PNG, brokenImages, fixtures, login, moneyRegex, reportDate, requireCredentials, requireStack } from './helpers';

// A first report opens at 0; the user types the cash added to the drawer.
const OPENING = 0;
const ADDITION = 1050;
const CASH = 300.1;
const VISA = 200.2;
const ALIPAY = 0.3;
const FOODPANDA = 99.99;
const EXPENSE = 25.1; // cash paths sum to whole dollars: HKD's catalogue has no sub-dollar coins here
const DEPOSIT = 500;
const CLOSING = OPENING + ADDITION + CASH - EXPENSE - DEPOSIT; // 825.00

test.describe.serial('daily closing', () => {
  const day = reportDate(-1);
  let entityId = '';

  test.beforeEach(async ({ page }) => {
    await requireStack();
    const creds = requireCredentials();
    entityId = creds.entityId;
    await login(page, creds);
  });

  // The company's own address since 2026-10-05: the full id 308s to /entity/<shortid>/<name>/...
  const stepUrl = (step: string) => `/entity/${entityId}/petty-cash/reports/new/${step}?transaction_date=${day}`;
  /** A wizard page under the company's address, before (`new`) or after the report has an id. */
  const atStep = (step: string) => new RegExp(`/entity/[0-9a-f]{8}/[^/]+/petty-cash/reports/(new|[0-9a-f-]{36})/${step}(\\?|$)`);
  const saveAndNext = (page: Page) => page.getByRole('button', { name: 'Save & Next' });

  test('addition to drawer: the opening balance updates live', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(stepUrl('opening'));
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Addition to Drawer');
    // Step progress: five stages, this one current (Part 14)
    await expect(page.locator('.pc-steps li')).toHaveCount(5);
    await expect(page.locator('.pc-steps li[aria-current="step"]')).toContainText('Drawer');
    await expect(page.locator('input[name="transaction_date"]')).toHaveValue(day);
    await expect(page.locator('#startingCashBalance')).toHaveText(moneyRegex(OPENING));
    await page.locator('input[name="cash_addition"]').fill(String(ADDITION));
    await page.locator('input[name="cash_addition"]').blur();
    await expect(page.locator('#openingCashBalance')).toHaveText(moneyRegex(OPENING + ADDITION));
    await saveAndNext(page).click();
    await expect(page).toHaveURL(atStep('sale'));
    expect(errors).toEqual([]);
  });

  test('sales: per-method amounts and live sub-totals', async ({ page }) => {
    await page.goto(stepUrl('sale'));
    await page.locator('#shop_sales_cash').fill(String(CASH));
    await page.locator('#shop_sales_visa').fill(String(VISA));
    await page.locator('#shop_sales_alipay').fill(String(ALIPAY));
    await page.locator('#delivery_sales_foodpanda').fill(String(FOODPANDA));
    await page.locator('#delivery_sales_foodpanda').blur();
    await expect(page.locator('#totalElectronicSales')).toHaveText(moneyRegex(VISA + ALIPAY));
    await expect(page.locator('#totalDeliverySales')).toHaveText(moneyRegex(FOODPANDA));
    await expect(page.locator('#totalCashSales')).toHaveText(moneyRegex(CASH));
    await expect(page.locator('#totalSales')).toHaveText(moneyRegex(CASH + VISA + ALIPAY + FOODPANDA));
    await saveAndNext(page).click();
    await expect(page).toHaveURL(atStep('expense'));
  });

  test('expenses: an empty entry is refused with every problem named', async ({ page }) => {
    await page.goto(stepUrl('expense'));
    await page.getByRole('button', { name: /add expense/i }).first().click();
    const drawer = page.locator('#expenseDrawer');
    await expect(drawer).toBeVisible();
    await drawer.getByRole('button', { name: 'Add expense' }).click();
    // two or more problems: the error summary takes focus and names each (CLAUDE.md validation)
    const summary = drawer.locator('[data-pc-summary]');
    await expect(summary).toBeVisible();
    await expect(summary).toBeFocused();
    await expect(summary).toContainText('The amount is still empty');
    await expect(summary).toContainText('The receipt is still missing');
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
  });

  test('expenses: one entry with a receipt is added and totalled', async ({ page }) => {
    await page.goto(stepUrl('expense'));
    await page.getByRole('button', { name: /add expense/i }).first().click();
    const drawer = page.locator('#expenseDrawer');
    await page.locator('#expense_files').setInputFiles({ name: 'receipt.png', mimeType: 'image/png', buffer: RECEIPT_PNG });
    await expect(drawer.locator('#newReceipts')).toContainText('receipt.png');
    await page.locator('#expense_amount').fill(String(EXPENSE));
    await page.locator('#expense_remarks').fill('Tape');
    // supplier and account: comboboxes over the entity's synced contacts and accounts
    const fx = fixtures();
    await page.locator('#expense_contact').fill(fx.supplierQuery);
    await page.locator('#expenseContactSuggestions [role="option"]').filter({ hasText: fx.supplierName }).first().dispatchEvent('mousedown');
    await page.locator('#expense_account_code').fill(fx.accountQuery);
    await page.locator('#expenseAccountSuggestions [role="option"]').filter({ hasText: fx.accountName }).first().dispatchEvent('mousedown');
    await drawer.getByRole('button', { name: 'Add expense' }).click();
    // saved at once; the list and the total come back from the server
    await expect(page.locator('#jinjaExpenses')).toContainText(fx.accountName);
    await expect(page.locator('#grossTotal')).toHaveText(moneyRegex(EXPENSE));
    await saveAndNext(page).click();
    // the old deposit step goes on to Cash Count, where the deposit is now the first block
    await expect(page).toHaveURL(atStep('cash-count'));
  });

  test('expenses: the stored receipt opens full screen from the entry, never a new tab', async ({ page }) => {
    await page.goto(stepUrl('expense'));
    await page.locator('[data-pc-open-expense]').first().click();
    const drawer = page.locator('#expenseDrawer');
    await expect(drawer).toBeVisible();
    await expect(page.locator('#expense_account_code')).toHaveValue(new RegExp(fixtures().accountName));
    const popups: string[] = [];
    page.context().on('page', (p) => popups.push(p.url()));
    await drawer.locator('#existingReceipts [data-receipt-key]').first().click();
    await expect(page.locator('#receiptViewerModal')).toBeVisible();
    expect(await brokenImages(page, '#receiptViewerModal')).toEqual([]);
    // Escape closes the viewer only; the drawer under it stays
    await page.keyboard.press('Escape');
    await expect(page.locator('#receiptViewerModal')).toBeHidden();
    await expect(drawer).toBeVisible();
    expect(popups).toEqual([]);
  });

  test('expenses: a picked PDF receipt opens in the viewer, never a new tab or a download', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(stepUrl('expense'));
    await page.getByRole('button', { name: /add expense/i }).first().click();
    await page.locator('#expense_files').setInputFiles({ name: 'receipt.pdf', mimeType: 'application/pdf', buffer: RECEIPT_PDF });
    const popups: string[] = [];
    page.context().on('page', (p) => popups.push(p.url()));
    const downloads: string[] = [];
    page.on('download', (d) => downloads.push(d.suggestedFilename()));
    await page.locator('#newReceipts').getByRole('button', { name: 'View' }).click();
    await expect(page.locator('#receiptViewerModal canvas')).toHaveCount(1, { timeout: 20_000 });
    await page.keyboard.press('Escape');
    await expect(page.locator('#receiptViewerModal')).toBeHidden();
    expect(popups).toEqual([]);
    expect(downloads).toEqual([]);
    expect(errors).toEqual([]);
  });

  test('cash count: the deposit, then a count that matches, and no reason needed', async ({ page }) => {
    await page.goto(stepUrl('cash-count'));
    // opening + addition + cash sales - expenses, i.e. what is in the drawer before the deposit
    await expect(page.locator('#currentBalanceDisplay')).toContainText(moneyRegex(OPENING + ADDITION + CASH - EXPENSE));
    await page.locator('#bank_deposit').fill(String(DEPOSIT));
    await page.locator('#bank_deposit').blur();
    await expect(page.locator('#expected_cash_count_balance')).toHaveText(moneyRegex(CLOSING));
    // one task at a time: Save & Next waits for the count
    await expect(saveAndNext(page)).toBeDisabled();
    await expect(page.locator('#nextReason')).toHaveText('Count the drawer to continue');
    // 825 = 500 + 100x3 + 20 + 5, counted in the sheet (labelled rows, a live total)
    await page.getByRole('button', { name: 'Count notes and coins' }).click();
    const sheet = page.locator('#countSheet');
    await expect(sheet).toBeVisible();
    const counts: Record<string, string> = { '500': '1', '100': '3', '20': '1', '5': '1' };
    const inputs = sheet.locator('input[data-denomination]');
    const n = await inputs.count();
    expect(n).toBeGreaterThan(5);
    for (let i = 0; i < n; i++) {
      const el = inputs.nth(i);
      const face = Number(await el.getAttribute('data-denomination'));
      const hit = Object.entries(counts).find(([f]) => Number(f) === face);
      await el.fill(hit ? hit[1] : '');
    }
    await expect(sheet.locator('#sheetTotal')).toHaveText(moneyRegex(CLOSING));
    await sheet.getByRole('button', { name: 'Save count' }).click();
    await expect(sheet).toBeHidden();
    await page.locator('#safeBoxBalance').fill('0');
    await page.locator('#safeBoxBalance').blur();
    await expect(page.locator('#cash_count_balance')).toHaveText(moneyRegex(CLOSING));
    await expect(page.locator('#variance')).toHaveText('None');
    await expect(page.locator('#reasonField')).toBeHidden();
    await saveAndNext(page).click();
    await expect(page).toHaveURL(atStep('ending'));
  });

  test('cash count: a difference holds Save & Next until it has a reason', async ({ page }) => {
    await page.goto(stepUrl('cash-count'));
    // the saved count opens done; Edit reopens the sheet
    const sheet = page.locator('#countSheet');
    const recount = async (value: string) => {
      await page.getByRole('button', { name: 'Edit the count' }).click();
      await expect(sheet).toBeVisible();
      await sheet.locator('input[data-denomination="5.0"], input[data-denomination="5"]').first().fill(value);
      await sheet.getByRole('button', { name: 'Save count' }).click();
      await expect(sheet).toBeHidden();
    };
    // the HKD 5 coin: take it out of the count and the drawer is 5 short
    await recount('');
    await expect(page.locator('#variance')).toHaveText(/short$/);
    await expect(saveAndNext(page)).toBeDisabled();
    await expect(page.locator('#nextReason')).toHaveText('Add a reason for the difference to continue.');
    await page.locator('#discrepancyDescription').fill('Float swap');
    await expect(saveAndNext(page)).toBeEnabled();
    // put the count back: the journey's report is exact
    await recount('1');
    await expect(page.locator('#variance')).toHaveText('None');
  });

  test('close: every stage on one page, then the outcome page', async ({ page }) => {
    await page.goto(stepUrl('ending'));
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Close');
    const summary = page.locator('main');
    // one row per stage (Daily Closing Phase 1): totals, not each sales method
    for (const amount of [CASH + VISA + ALIPAY + FOODPANDA, CASH, EXPENSE, DEPOSIT, CLOSING]) {
      await expect(summary).toContainText(moneyRegex(amount));
    }
    await expect(summary.getByRole('link', { name: /^Edit / })).toHaveCount(4);
    await page.getByRole('button', { name: 'Submit Daily Report' }).click();
    await expect(page).toHaveURL(atStep('submitted'));
    await expect(page.locator('#outcome-title')).toBeFocused();
    await expect(page.locator('main')).toContainText(moneyRegex(CLOSING)); // Cash counted
  });

  test('history and the Daily Report show the posted day with the same figures', async ({ page }) => {
    await page.goto(`/entity/${entityId}/petty-cash/reports`);
    const [y, m, d] = day.split('-').map(Number);
    const monthName = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1];
    const results = page.locator('main');
    // "Tue 15 Sep 2026 · Expenses HKD 25.10 · Submitted by Tess · HKD 600.59 Sales · Submitted"
    await expect(results).toContainText(new RegExp(`${d} ${monthName} ${y}`));
    await expect(results).toContainText(moneyRegex(CASH + VISA + ALIPAY + FOODPANDA));
    await expect(results).toContainText(moneyRegex(EXPENSE));
    await expect(results).toContainText(/Submitted by Tess/);
    await page.locator('.pc-row__link').first().click();
    await expect(page).toHaveURL(/\/entity\/[0-9a-f]{8}\/[^/]+\/petty-cash\/reports\/([0-9a-f-]{36})\/summary/);
    const report = page.locator('main');
    // the outcome band: Cash position is the hero, Total sales and Total expenses beside it
    await expect(report.locator('.pc-band__label')).toHaveText(['Cash position', 'Total sales', 'Total expenses']);
    await expect(report).toContainText(moneyRegex(CASH + VISA + ALIPAY + FOODPANDA));
    await expect(report).toContainText(moneyRegex(EXPENSE));
    // the expense lines sit in the collapsed Expenses section, named by their ACCOUNT
    await report.getByText(/^Expenses \(\d+\)$/).click();
    await expect(report).toContainText(fixtures().accountName);
  });

  test('the movements CSV lists the posted day, one line per movement', async ({ page }) => {
    const res = await page.request.get(`/entity/${entityId}/petty-cash/reports/download-csv?start_date=${day}&end_date=${day}`);
    expect(res.status()).toBe(200);
    const text = await res.text();
    const rows = text.split(/\r?\n/).filter((r) => r.trim());
    expect(rows[0]).toMatch(/^Date,Account Code,Amount/);
    // Python writes the amounts: a whole number keeps its ".0" (500.0), any other as typed
    const amount = (n: number) => (Number.isInteger(n) ? n.toFixed(1) : String(n));
    expect(text).toContain('Cash Addition');
    expect(text).toContain(`,${fixtures().expenseCode},${amount(-EXPENSE)},Tape`);
    expect(text).toContain(`,200,${amount(CASH)},Cash Sale`);
    expect(text).toContain(`,${fixtures().pettyCashCode},${amount(-DEPOSIT)},Bank Deposit`);
  });
});
