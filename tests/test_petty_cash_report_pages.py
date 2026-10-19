"""The redesigned pages around the Daily Closing, rendered through the routes (Parts 13-15):

- Close (15.15e): the read-only work verification with Edit links, one "Submit Daily Report";
- the outcome page (15.12e): the facts from the server, Publish to Xero behind a confirmation;
- the Daily Report (15.7): the outcome band (Cash position as the hero, Total sales and Total
  expenses beside it), the difference stated as fact, the sales mix and expenses-by-account charts
  (server data, each with its table), Share and More (Edit / Delete), and on a share link no
  actions and no navigation;
- report history (15.4b): status chips and rows per page in the URL, rows that open the report.
"""
from __future__ import annotations

import re
from decimal import Decimal

import pytest

import char_factories as F
from test_char_report_lifecycle import (REPORT_DATE, count_exactly, open_report, post_cash_count, post_deposit,
                                        post_ending, post_expenses, post_report, post_sales)

from blueprints.report.services.report_page import expense_bars, sales_mix

pytestmark = pytest.mark.char


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def s3(monkeypatch):
    return F.install_fake_s3(monkeypatch)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        F.seed_sales_methods(db, owner, entity, electronic=("Visa",), delivery=("Foodpanda",))
    return owner, entity


def get(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code, resp.data[:300])
    return resp.get_data(as_text=True)


def primaries(html):
    body = html.split('<main class="pc-main"', 1)[1].split("</main>", 1)[0]
    return re.findall(r'class="pc-btn pc-btn--primary[^"]*"[^>]*>([^<]*)<', body)


def test_close_is_the_work_verification(shop, client):
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, opening="1000.00")
    post_sales(client, entity, REPORT_DATE, cash="300.00", by_method={"visa_sales": "120.00"})
    post_expenses(client, entity, REPORT_DATE, [("Tape", "25.00")])
    faces = F.denomination_fields(client.application, entity.id).values()
    post_cash_count(client, entity, REPORT_DATE, count_exactly(Decimal("1275.00"), faces))  # 1000 + 300 - 25

    html = get(client, f"{F.co(client, entity.id)}/petty-cash/reports/new/ending?transaction_date={F.iso(REPORT_DATE)}")

    assert "<h1" in html and ">Close</h1>" in html
    assert primaries(html) == ["Submit Daily Report"]
    for section in ("Addition to Drawer", "Sales", "Expenses (1)", "Cash Count"):
        assert section in html
    assert html.count('aria-label="Edit ') == 4  # one Edit link per stage
    # one row per stage with its total (Daily Closing Phase 1): sales 300 + Visa 120, expenses, the count
    assert "HKD 420.00" in html and "HKD 25.00" in html and "HKD 1,275.00" in html
    assert "Ready to submit" in html
    assert 'name="action_type" value="submit"' in html
    for gone in ("pie_chart", "bar_chart", "cdn.tailwindcss.com", "salesHistory"):
        assert gone not in html


def test_the_outcome_page_draws_the_server_facts(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity)

    html = get(client, f"{F.co(client, entity.id)}/petty-cash/reports/{report_id}/submitted")

    assert "report is submitted" in html
    assert "Sales" in html and "Expenses" in html and "Cash counted" in html and "Not sent to Xero yet" in html
    assert f"HKD {closing:,.2f}" in html
    assert 'id="publishButton"' in html and 'id="publishReportModal"' in html  # asks before Xero
    assert "/summary" in html  # View report
    assert 'id="outcome-title" tabindex="-1"' in html


def test_the_daily_report_has_the_outcome_band_and_more(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity)

    html = get(client, f"{F.co(client, entity.id)}/petty-cash/reports/{report_id}/summary")

    assert ">Daily Report</h1>" in html
    band = html.split('<section class="pc-band"', 1)[1].split("</section>", 1)[0]
    assert re.findall(r'class="pc-band__label"[^>]*>([^<]+)<', band) == ["Cash position", "Total sales", "Total expenses"]
    assert band.count("pc-band__amount") == 1  # the one hero amount
    assert re.search(r'class="pc-band__amount pc-num" translate="no">HKD ' + re.escape(f"{closing:,.2f}") + "<", band)
    assert ">HKD 300.00<" in band and ">HKD 25.00<" in band and "1 expense<" in band
    assert "Petty Cash" in band and 'img/safebox.webp" alt=""' in band
    assert "pc-kpi" not in html
    assert 'aria-label="More report actions"' in html
    assert 'id="editReportBtn"' in html and 'id="deleteReportBtn"' in html  # the latest report
    assert 'id="shareReportBtn"' in html
    assert 'data-tone="info">Submitted<' in html
    assert "Submitted by Olive Owner" in html


def test_a_shared_daily_report_has_no_actions_and_no_navigation(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)
    resp = client.post("/api/generate_share_link", json={"entity_id": entity.id, "transaction_date": F.iso(REPORT_DATE)})
    assert resp.status_code == 200, resp.data[:300]
    path = resp.get_json()["url"].split("/Minty_Report/", 1)[1]

    anonymous = app.test_client()
    html = get(anonymous, f"/Minty_Report/{path}")

    assert ">Daily Report</h1>" in html
    for gone in ("shareReportBtn", "More report actions", "data-sidebar-open", "minty-sidebar", "pc-appbar__back", "data-receipt-key"):
        assert gone not in html, gone
    assert entity.name in html


def test_history_rows_open_the_report_and_filter_by_status(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)
    base = f"{F.co(client, entity.id)}/petty-cash/reports"

    html = get(client, base)
    assert f"/petty-cash/reports/{report_id}/summary" in html
    assert "Showing 1–1 of 1" in html
    assert re.search(r'<a class="pc-chip" href="[^"]*"\s+aria-pressed="true">All</a>', html)

    assert report_id in get(client, base + "?status=submitted")
    drafts = get(client, base + "?status=draft")
    assert report_id not in drafts and "No reports match these filters" in drafts
    # an unknown status or page size falls back instead of failing
    assert report_id in get(client, base + "?status=nonsense&per_page=7")
    assert 'value="25" selected' in get(client, base + "?per_page=25")


def test_history_exports_csv_only_for_a_date_range(shop, client):
    owner, entity = shop
    F.login(client, owner)
    post_report(client, entity)
    base = f"{F.co(client, entity.id)}/petty-cash/reports"

    assert "Choose both dates to export." in get(client, base)
    ranged = get(client, base + f"?start_date={F.iso(REPORT_DATE)}&end_date={F.iso(REPORT_DATE)}")
    assert "/download-csv?" in ranged and "Choose both dates to export." not in ranged


# ---- Where the money came from and went (15.7): the server's chart data, then the page

class _Sale:
    def __init__(self, value_name):
        self.value_name = value_name


def test_the_sales_mix_runs_largest_first_and_leaves_out_what_sold_nothing():
    visa, alipay = _Sale("visa_sales"), _Sale("alipay_sales")
    mix = sales_mix([(visa, None, "100.00"), (alipay, None, 0), (None, "Cash", Decimal("200.00")),
                     (_Sale("octopus_sales"), None, "33.33")])

    assert [(m["label"] or m["sale"].value_name, m["amount"]) for m in mix] == [
        ("Cash", Decimal("200.00")), ("visa_sales", Decimal("100.00")), ("octopus_sales", Decimal("33.33"))]
    assert [m["pct"] for m in mix] == [60, 30, 10]
    assert sum(m["width"] for m in mix) == pytest.approx(100, abs=0.05)
    assert [m["tone"] for m in mix] == [1, 2, 3]


def test_the_sales_mix_shares_always_add_up_to_100():
    for amounts in (("1", "1", "1"), ("120", "300"), ("0.01", "999.99"), ("10",) * 7, ("33.33", "33.33", "33.34")):
        mix = sales_mix([(None, f"m{i}", a) for i, a in enumerate(amounts)])
        assert sum(m["pct"] for m in mix) == 100, amounts
    # six tones, so neighbours never share one
    assert [m["tone"] for m in sales_mix([(None, f"m{i}", 1) for i in range(7)])] == [1, 2, 3, 4, 5, 6, 1]


def test_one_sales_method_is_the_whole_bar_and_no_sales_is_no_bar():
    assert [(m["label"], m["pct"], m["width"]) for m in sales_mix([(None, "Cash", "300")])] == [("Cash", 100, 100.0)]
    assert sales_mix([(None, "Cash", 0), (_Sale("visa_sales"), None, None)]) == []


def test_expense_bars_sum_per_account_largest_first():
    bars = expense_bars([("Office supplies", "25.00"), ("Staff meals", "40"), ("Office supplies", Decimal("10.00")),
                         (None, "5.00"), ("Cleaning", "40.00")])

    assert [(b["name"], b["amount"]) for b in bars] == [
        ("Cleaning", Decimal("40.00")), ("Staff meals", Decimal("40.00")),  # a tie reads by name
        ("Office supplies", Decimal("35.00")), ("No account", Decimal("5.00"))]
    assert [b["width"] for b in bars] == [100.0, 100.0, 87.5, 12.5]  # a share of the largest


def test_no_expenses_is_no_bars():
    assert expense_bars([]) == []
    assert expense_bars([("Office supplies", 0)]) == []


def test_the_daily_report_charts_the_money_with_its_tables(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, opening="1000.00")
    post_sales(client, entity, REPORT_DATE, cash="300.00", by_method={"visa_sales": "120.00"})
    post_expenses(client, entity, REPORT_DATE, [("Tape", "25.00"), ("Milk", "40.00"), ("Pens", "10.00")])
    post_deposit(client, entity, REPORT_DATE, "0")
    faces = F.denomination_fields(client.application, entity.id).values()
    post_cash_count(client, entity, REPORT_DATE, count_exactly(Decimal("1225.00"), faces))  # 1000 + 300 - 75
    resp = post_ending(client, entity, REPORT_DATE)
    report_id = re.search(r"/reports/([0-9a-f-]{36})/submitted", resp.headers["Location"]).group(1)
    with app.app_context():
        from models.db import AccountInfo, ShopExpense
        from models.db import db as _db

        office = AccountInfo(entity_id=entity.id, type="EXPENSE", name="Office supplies", xero_code="429")
        meals = AccountInfo(entity_id=entity.id, type="EXPENSE", name="Staff meals", xero_code="420")
        _db.session.add_all([office, meals])
        _db.session.flush()
        for line in ShopExpense.query.filter_by(report_id=report_id).all():
            line.account = meals if line.item == "Milk" else office
        _db.session.commit()

    html = get(client, f"{F.co(client, entity.id)}/petty-cash/reports/{report_id}/summary")

    flow = html.split('<section class="pc-card pc-flow"', 1)[1].split("</section>", 1)[0]
    assert "Where the money came from and went" in flow
    # the proportion bar: one description for a screen reader; the legend names every segment
    assert 'role="img" aria-label="Sales by method: Cash HKD 300.00, 71%; Visa HKD 120.00, 29%"' in flow
    assert flow.count('class="pc-stackbar__seg"') == 2
    assert re.findall(r'pc-legend__name">([^<]+)<', flow) == ["Cash", "Visa"]
    # the bar rows: summed per account, largest first, each named with its amount
    assert re.findall(r'pc-barrow__name">([^<]+)</span>\s*<span class="pc-barrow__amount pc-num" translate="no">([^<]+)<',
                      flow) == [("Staff meals", "HKD 40.00"), ("Office supplies", "HKD 35.00")]
    # the table alternatives stay, after the charts: the collapsed breakdown lists
    after = html.split(flow, 1)[1]
    assert "<summary><span>Sales by method</span>" in after and "<summary><span>Expenses (3)</span>" in after
    assert ">HKD 120.00<" in after and ">HKD 40.00<" in after


def test_a_one_method_no_expense_report_draws_one_bar_and_says_no_expenses(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity, expenses=())

    html = get(client, f"{F.co(client, entity.id)}/petty-cash/reports/{report_id}/summary")

    flow = html.split('<section class="pc-card pc-flow"', 1)[1].split("</section>", 1)[0]
    assert flow.count('class="pc-stackbar__seg"') == 1
    assert 'aria-label="Sales by method: Cash HKD 300.00, 100%"' in flow
    assert "No expenses this day." in flow and "pc-barrow" not in flow
