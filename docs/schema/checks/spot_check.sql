-- ===========================================================================
-- Spot check: three entities, before and after, side by side.
--
--     psql "$URL" -f docs/schema/checks/spot_check.sql
--
-- Against a database rehearse.py has loaded (pettycashv2 at head beside a
-- filled pettycash_test). Picks the three entities with the most posted
-- reports and prints, for each, what a person would compare on screen: report
-- count, sales, expenses, cash counted, per-method sales, bills and their
-- audit rows. Every "diff" column must be 0.
-- ===========================================================================
\pset format aligned
\pset border 2

WITH top3 AS (
  SELECT e.id, e.name
    FROM pettycashv2.entities e
    JOIN pettycashv2.report r ON r.company = e.id AND r.status = 'posted'
   GROUP BY e.id, e.name ORDER BY count(*) DESC LIMIT 3
),
src AS (
  SELECT t.name,
         count(r.id)                                              AS reports,
         round(coalesce(sum(r.total_sales),0)::numeric, 2)        AS sales,
         round(coalesce(sum(r.expenses),0)::numeric, 2)           AS expenses,
         round(coalesce(sum(r.actual_cash_total),0)::numeric, 2)  AS cash_counted,
         (SELECT round(coalesce(sum(se.amount),0)::numeric, 2) FROM pettycashv2.shop_expense se
           WHERE se.report_id IN (SELECT id FROM pettycashv2.report WHERE company = t.id)) AS expense_lines,
         (SELECT count(*) FROM pettycashv2.bill b WHERE b.entity_id = t.id) AS bills,
         (SELECT round(coalesce(sum(b.amount),0), 2) FROM pettycashv2.bill b WHERE b.entity_id = t.id) AS bill_amount,
         (SELECT count(*) FROM pettycashv2.audit a JOIN pettycashv2.bill b ON b.id = a.bill_id WHERE b.entity_id = t.id) AS bill_audit
    FROM top3 t
    LEFT JOIN pettycashv2.report r ON r.company = t.id
     AND EXISTS (SELECT 1 FROM pettycash_test.report d WHERE d.id = r.id::uuid)   -- the rows the load kept
   GROUP BY t.id, t.name
),
dst AS (
  SELECT e.name,
         count(r.id)                                   AS reports,
         round(coalesce(sum(r.total_sales),0), 2)      AS sales,
         round(coalesce(sum(r.expense_total),0), 2)    AS expenses,
         round(coalesce(sum(v.actual_cash_total),0), 2) AS cash_counted,
         (SELECT round(coalesce(sum(x.amount),0), 2) FROM pettycash_test.report_expense x
           JOIN pettycash_test.report rr ON rr.id = x.report_id WHERE rr.entity_id = e.id) AS expense_lines,
         (SELECT count(*) FROM pettycash_test.bill b WHERE b.entity_id = e.id) AS bills,
         (SELECT round(coalesce(sum(b.amount),0), 2) FROM pettycash_test.bill b WHERE b.entity_id = e.id) AS bill_amount,
         (SELECT count(*) FROM pettycash_test.bill_audit a JOIN pettycash_test.bill b ON b.id = a.bill_id WHERE b.entity_id = e.id) AS bill_audit
    FROM top3 t
    JOIN pettycash_test.entities e ON e.id = t.id::uuid
    LEFT JOIN pettycash_test.report r ON r.entity_id = e.id
    LEFT JOIN pettycash_test.report_cash_summary v ON v.report_id = r.id
   GROUP BY e.id, e.name
)
SELECT s.name,
       s.reports, d.reports - s.reports AS reports_diff,
       s.sales, d.sales - s.sales AS sales_diff,
       s.expenses, d.expenses - s.expenses AS expenses_diff,
       s.expense_lines, d.expense_lines - s.expense_lines AS lines_diff,
       s.cash_counted, d.cash_counted - s.cash_counted AS cash_diff,
       s.bills, d.bills - s.bills AS bills_diff,
       s.bill_amount, d.bill_amount - s.bill_amount AS bill_amt_diff,
       s.bill_audit, d.bill_audit - s.bill_audit AS audit_diff
  FROM src s JOIN dst d ON d.name = s.name
 ORDER BY s.reports DESC;

-- Per-method sales for the same three entities: source rows by method name vs
-- target rows by catalogue name. Every diff must be 0.
WITH top3 AS (
  SELECT e.id, e.name
    FROM pettycashv2.entities e
    JOIN pettycashv2.report r ON r.company = e.id AND r.status = 'posted'
   GROUP BY e.id, e.name ORDER BY count(*) DESC LIMIT 3
),
src AS (
  SELECT t.name AS entity, si.name AS method, round(sum(x.amount)::numeric, 2) AS amount
    FROM top3 t
    JOIN pettycashv2.report r ON r.company = t.id
    JOIN pettycashv2.report_sale_detail x ON x.report_id = r.id
    JOIN pettycashv2.sale_info si ON si.id = COALESCE(x.sale_info_id,
         (SELECT ess.sale_info_id FROM pettycashv2.entity_sale_setting ess WHERE ess.sale_id = x.sale_id LIMIT 1))
   WHERE EXISTS (SELECT 1 FROM pettycash_test.report d WHERE d.id = r.id::uuid)
   GROUP BY 1, 2
),
dst AS (
  SELECT e.name AS entity, si.sale_name AS method, round(sum(x.amount), 2) AS amount
    FROM pettycash_test.entities e
    JOIN pettycash_test.report r ON r.entity_id = e.id
    JOIN pettycash_test.report_sale x ON x.report_id = r.id
    JOIN pettycash_test.sale_info si ON si.id = x.sale_id
   WHERE e.id IN (SELECT id::uuid FROM top3)
   GROUP BY 1, 2
)
SELECT s.entity, s.method, s.amount, d.amount - s.amount AS diff
  FROM src s FULL JOIN dst d ON d.entity = s.entity AND d.method = s.method
 ORDER BY 1, 3 DESC;
