"""The redesigned pages around the Daily Closing, rendered through the routes (Parts 13-15):

- Close (15.15e): the read-only work verification with Edit links, one "Submit Daily Report";
- the outcome page (15.12e): the facts from the server, Publish to Xero behind a confirmation;
- the Daily Report (15.7): 3 KPIs, the difference stated as fact, Share and More (Edit / Delete),
  and on a share link no actions and no navigation;
- report history (15.4b): status chips and rows per page in the URL, rows that open the report.
"""
from __future__ import annotations

import re
from decimal import Decimal

import pytest

import char_factories as F
from test_char_report_lifecycle import (REPORT_DATE, count_exactly, open_report, post_cash_count, post_expenses,
                                        post_report, post_sales)

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


def test_the_daily_report_has_three_kpis_and_more(shop, client):
    owner, entity = shop
    F.login(client, owner)
    report_id, _ = post_report(client, entity)

    html = get(client, f"{F.co(client, entity.id)}/petty-cash/reports/{report_id}/summary")

    assert ">Daily Report</h1>" in html
    assert re.findall(r'class="pc-kpi__label">([^<]+)<', html) == ["Total sales", "Total expenses", "Cash position"]
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
