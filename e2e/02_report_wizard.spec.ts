// The petty-cash report wizard in a real browser: opening -> sales -> expenses -> deposit ->
// cash count -> ending -> submitted. This is the JavaScript the schema redesign can break
// silently (field names, JSON keys), so every step asserts what the page SHOWS, not what the
// database holds. Amounts are chosen so each total is a distinct number.
import { expect, test, type Page } from '@playwright/test';
import { login, moneyRegex, reportDate, requireCredentials, requireStack } from './helpers';

// A first report opens at 0 (the page carries yesterday's closing in a hidden field); the
// user types the cash added to the float.
const OPENING = 0;
const ADDITION = 1050;
const CASH = 300.1;
const VISA = 200.2;
const ALIPAY = 0.3;
const FOODPANDA = 99.99;
const EXPENSE = 25.1; // cash paths sum to whole dollars: HKD's catalogue has no sub-dollar coins here
const DEPOSIT = 500;
const CLOSING = OPENING + ADDITION + CASH - EXPENSE - DEPOSIT; // 825.00

test.describe.serial('report wizard', () => {
  const day = reportDate(-1);
  let entityId = '';

  test.beforeEach(async ({ page }) => {
    await requireStack();
    const creds = requireCredentials();
    entityId = creds.entityId;
    await login(page, creds);
  });

  const stepUrl = (step: string) => `/report/${step}?entity_id=${entityId}&transaction_date=${day}`;
  const next = (page: Page) => page.getByRole('button', { name: /save.*next|next|continue/i }).first();

  test('opening: cash addition is accepted and the opening balance updates live', async ({ page }) => {
    await page.goto(stepUrl('opening'));
    await expect(page.locator('input[name="transaction_date"]')).toHaveValue(day);
    await expect(page.locator('#startingCashBalance')).toHaveText(moneyRegex(OPENING));
    await page.locator('input[name="cash_addition"]').fill(String(ADDITION));
    await page.locator('input[name="cash_addition"]').blur();
    await expect(page.locator('#openingCashBalance')).toHaveText(moneyRegex(OPENING + ADDITION));
    await next(page).click();
    await expect(page).toHaveURL(/\/report\/sale/);
  });

  test('sales: per-method amounts and a live total', async ({ page }) => {
    await page.goto(stepUrl('sale'));
    await page.locator('#shop_sales_cash').fill(String(CASH));
    await page.locator('#shop_sales_visa').fill(String(VISA));
    await page.locator('#shop_sales_alipay').fill(String(ALIPAY));
    await page.locator('#delivery_sales_foodpanda').fill(String(FOODPANDA));
    await page.locator('#delivery_sales_foodpanda').blur();
    // the page's own JavaScript computes the three sub-totals before anything is saved
    await expect(page.locator('#totalElectronicSales')).toHaveText(moneyRegex(VISA + ALIPAY));
    await expect(page.locator('#totalDeliverySales')).toHaveText(moneyRegex(FOODPANDA));
    await expect(page.locator('#totalCashSales')).toHaveText(moneyRegex(CASH));
    await next(page).click();
    await expect(page).toHaveURL(/\/report\/expense/);
  });

  test('expenses: one line with a receipt is added and totalled', async ({ page }) => {
    await page.goto(stepUrl('expense'));
    await page.getByRole('button', { name: /add new expense/i }).click();
    await page.locator('#expense_files').setInputFiles({
      name: 'receipt.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('ÿØÿàfake-jpeg-bytes', 'binary'),
    });
    await page.locator('#expense_amount').fill(String(EXPENSE));
    await page.locator('#expense_remarks').fill('Tape');
    // supplier and account are searchable inputs fed by the entity's synced contacts/accounts
    await page.locator('#expense_contact').fill('E2E Stationery');
    await page.locator('#expenseContactSuggestions').getByText('E2E Stationery Supplier').first().click();
    await page.locator('#expense_account_code').fill('Office');
    await page.locator('#expenseAccountSuggestions').getByText('E2E Office Expenses 429').first().click();
    await page.locator('#addExpenseForm button[onclick="addExpense()"]').click();
    // the new line appears in the list with its description and amount, and the total moves
    await expect(page.getByText('Tape').first()).toBeVisible();
    await expect(page.getByText(moneyRegex(EXPENSE)).first()).toBeVisible();
    await next(page).click();
    await expect(page).toHaveURL(/\/report\/deposit/);
  });

  test('deposit: the page shows the cash on hand before the deposit', async ({ page }) => {
    await page.goto(stepUrl('deposit'));
    // opening + addition + cash sales - expenses, i.e. what is in the till to deposit from
    await expect(page.locator('#currentBalanceDisplay')).toContainText(moneyRegex(OPENING + ADDITION + CASH - EXPENSE));
    await page.locator('#bank_deposit').fill(String(DEPOSIT));
    await page.locator('#bank_deposit').blur();
    await next(page).click();
    await expect(page).toHaveURL(/\/report\/cash_count/);
  });

  test('cash count: denominations entered in the calculator add up to the closing balance', async ({ page }) => {
    await page.goto(stepUrl('cash_count'));
    // 825 = 500 + 100x3 + 20 + 5  (the counts live in a calculator modal; applying it writes
    // the hidden actual_cash[...] fields the form posts)
    const counts: Record<string, string> = { '500': '1', '100': '3', '20': '1', '5': '1' };
    await page.locator('#calculatorBtn').click();
    const inputs = page.locator('#calculatorModal input[data-denomination]');
    const n = await inputs.count();
    expect(n).toBeGreaterThan(5);
    for (let i = 0; i < n; i++) {
      const el = inputs.nth(i);
      const face = Number(await el.getAttribute('data-denomination'));
      const hit = Object.entries(counts).find(([f]) => Number(f) === face);
      await el.fill(hit ? hit[1] : '0');
    }
    await expect(page.locator('#cash_count_balance')).toContainText(moneyRegex(CLOSING));
    await page.locator('#applyCalculatorTotal').click();
    // applying writes each count to the hidden field the form posts, and the page compares the
    // total against the expected balance: no variance when the count is exact
    await expect(page.locator('#hidden_note500')).toHaveValue('1');
    await expect(page.locator('#hidden_note100')).toHaveValue('3');
    await expect(page.getByText(moneyRegex(CLOSING)).first()).toBeVisible(); // "Expected Cash Count Balance"
    await expect(page.locator('#discrepancyAmount')).toHaveValue(/^-?0(\.0+)?$/);
    await expect(page.locator('#discrepancyDescription')).toHaveAttribute('placeholder', /no discrepancy/i);
    await page.locator('#safeBoxBalance').fill('0');
    await next(page).click();
    await expect(page).toHaveURL(/\/report\/ending/);
  });

  test('cash count: the Actual Cash Balance field shows the applied total', async ({ page }) => {
    test.fail(true,
      'FINDING F4 (templates/report/cash_count.html applyCalculatorTotal): the calculator total is parsed after '
      + 'stripping only "$", but the page renders the currency CODE ("HKD"), so parseFloat gets NaN and the '
      + 'field shows HKD0.00. Display only - the posted counts and discrepancy come from the hidden fields. '
      + 'Fix in phase C4 (the page is rewritten for report_cash_count anyway); this test then starts passing.');
    await page.goto(stepUrl('cash_count'));
    // a reload shows the SAVED total correctly (rendered server-side); the defect is the value the
    // page writes right after Apply, so apply the calculator again and read the field before any reload
    await page.locator('#calculatorBtn').click();
    await page.locator('#applyCalculatorTotal').click();
    await expect(page.locator('#actualCashBalance')).toHaveValue(moneyRegex(CLOSING));
  });

  test('ending: the summary shows every figure and finishing lands on submitted', async ({ page }) => {
    await page.goto(stepUrl('ending'));
    const summary = page.locator('body');
    // total sales and its three-way split, total expenses, and the closing cash balance
    await expect(summary).toContainText(moneyRegex(CASH + VISA + ALIPAY + FOODPANDA));
    await expect(summary).toContainText(moneyRegex(VISA + ALIPAY));
    await expect(summary).toContainText(moneyRegex(FOODPANDA));
    await expect(summary).toContainText(moneyRegex(CASH));
    await expect(summary).toContainText(moneyRegex(EXPENSE));
    await expect(summary).toContainText(moneyRegex(CLOSING));
    await page.locator('#finishReportBtn').click();
    await expect(page).toHaveURL(/\/report\/[0-9a-f-]{36}\/submitted/);
  });

  test('history and detail show the posted report with the same figures', async ({ page }) => {
    await page.goto(`/entity/${entityId}/reports`);
    const [y, m, d] = day.split('-').map(Number);
    const monthName = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'][m - 1];
    const results = page.locator('body');
    // "15 SEP 2026 TUE  Sales HKD600.59  Expenses HKD25.10  Submitted ... by Eve"
    await expect(results).toContainText(new RegExp([d, monthName, y].join('[ ]+'), 'i'));
    await expect(results).toContainText(moneyRegex(CASH + VISA + ALIPAY + FOODPANDA));
    await expect(results).toContainText(moneyRegex(EXPENSE));
    await expect(results).toContainText(/by Eve/);
    // "View Report" opens the ending summary of the posted report
    await page.getByRole('link', { name: /view report/i }).first().click();
    await expect(page).toHaveURL(/\/entity\/[0-9a-f-]{36}\/ending\/[0-9a-f-]{36}/);
    const detail = page.locator('body');
    // the summary: total sales, the three-way split, total expenses, closing cash balance
    for (const amount of [CASH + VISA + ALIPAY + FOODPANDA, VISA + ALIPAY, FOODPANDA, CASH, EXPENSE, CLOSING]) {
      await expect(detail).toContainText(moneyRegex(amount));
    }
    // the expense lines sit behind "Show more"; a line is named by its ACCOUNT (the remark
    // "Tape" is the description and is not shown here)
    await page.locator('#expensesShowMore').click();
    await expect(detail).toContainText('E2E Office Expenses 429');
  });
});
