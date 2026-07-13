/**
 * Shared currency input formatting for the report steps.
 *
 * Behavior (identical on every money input across Opening, Sales, Expense,
 * Deposit and Cash Count):
 *   - digits and a single decimal point only
 *   - at most MAX_INTEGER_DIGITS digits before the decimal point
 *   - at most 2 digits after it
 *   - while typing the value is only cleaned, never re-grouped, so the caret
 *     is never pushed around
 *   - blur groups thousands and pads to 2 decimals ("12000" -> "12,000.00")
 *   - an empty value stays empty so the field's placeholder shows through
 *
 * Money inputs are marked up as <input type="text" inputmode="decimal">, which
 * is also the selector formatAllCurrencyFields() uses to format server-rendered
 * values on page load.
 */
(function (global) {
  'use strict';

  var MAX_INTEGER_DIGITS = 11;
  var MONEY_INPUT_SELECTOR = 'input[type="text"][inputmode="decimal"]';

  function addThousandsSeparators(wholeNumber) {
    return wholeNumber.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  /**
   * Strip everything that isn't a digit or a decimal point and enforce the
   * digit limits. Returns an ungrouped string, e.g. "12000.5".
   */
  function sanitize(rawValue) {
    var value = String(rawValue).replace(/[^\d.]/g, '');
    if (value === '') return '';

    var firstDot = value.indexOf('.');
    var whole = firstDot === -1 ? value : value.slice(0, firstDot);
    // Collapse any extra decimal points into a single fractional part.
    var fraction =
      firstDot === -1 ? null : value.slice(firstDot + 1).replace(/\./g, '');

    whole = whole.slice(0, MAX_INTEGER_DIGITS);
    if (fraction !== null) fraction = fraction.slice(0, 2);

    return fraction === null ? whole : whole + '.' + fraction;
  }

  /**
   * Group thousands and pad to exactly 2 decimals, e.g. "1234.5" -> "1,234.50".
   * Empty stays empty.
   */
  function group(value) {
    if (value === '') return '';

    var parts = value.split('.');
    var whole = parts[0] === '' ? '0' : parts[0];
    var fraction = parts.length > 1 ? parts[1] : '';
    while (fraction.length < 2) fraction += '0';

    return addThousandsSeparators(whole) + '.' + fraction;
  }

  /**
   * oninput handler: clean the value only. Commas are deliberately NOT added
   * here so the caret stays where the user put it.
   */
  function formatCurrency(input) {
    var value = sanitize(input.value);
    if (input.value !== value) input.value = value;
  }

  /**
   * onblur handler: group thousands and pad to 2 decimals.
   */
  function formatWithCommas(input) {
    input.value = group(sanitize(input.value));
  }

  /**
   * Read a formatted input value back as a number.
   */
  function parseMoney(value) {
    if (value === null || value === undefined) return 0;
    var cleaned = String(value).replace(/,/g, '').trim();
    if (cleaned === '' || cleaned === '-') return 0;
    return parseFloat(cleaned) || 0;
  }

  /**
   * Render a number for display, e.g. 1234.5 -> "1,234.50".
   */
  function formatMoney(amount) {
    var number = typeof amount === 'number' ? amount : parseMoney(amount);
    if (!isFinite(number)) number = 0;
    return number.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  /**
   * Format every server-rendered money input on the page. Safe to call more
   * than once, and on inputs that are already formatted.
   */
  function formatAllCurrencyFields(root) {
    var scope = root || document;
    var inputs = scope.querySelectorAll(MONEY_INPUT_SELECTOR);
    Array.prototype.forEach.call(inputs, function (input) {
      if (input.value && input.value.trim() !== '') {
        input.value = group(sanitize(input.value));
      }
    });
  }

  global.Currency = {
    MAX_INTEGER_DIGITS: MAX_INTEGER_DIGITS,
    MONEY_INPUT_SELECTOR: MONEY_INPUT_SELECTOR,
    sanitize: sanitize,
    group: group,
    formatCurrency: formatCurrency,
    formatWithCommas: formatWithCommas,
    parseMoney: parseMoney,
    formatMoney: formatMoney,
    formatAllCurrencyFields: formatAllCurrencyFields,
  };

  // The report templates call these from inline oninput/onblur attributes and
  // from their own scripts, so they have to be globals too.
  global.formatCurrency = formatCurrency;
  global.formatWithCommas = formatWithCommas;
  global.formatAllCurrencyFields = formatAllCurrencyFields;
  // Opening's page-load hook is spelled differently; keep the alias so its
  // existing call site keeps working.
  global.formatAllCurrencyOnLoad = formatAllCurrencyFields;

  function runOnLoad() {
    formatAllCurrencyFields();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runOnLoad);
  } else {
    runOnLoad();
  }
  // Catch values injected after first paint.
  setTimeout(runOnLoad, 100);
  setTimeout(runOnLoad, 500);
})(window);
