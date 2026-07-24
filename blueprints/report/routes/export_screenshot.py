# Report export and screenshot routes; delegates to app implementation.
# Export and screenshot: generate_pdf_report, report_screenshot. Logic
# moved from app.
import os
import threading
import time
from datetime import datetime
from typing import cast

from docxtpl import DocxTemplate
from flask import current_app as app
from flask import jsonify, request, send_file, url_for
from flask_login import current_user, login_required
from loguru import logger
from user_agents import parse

from blueprints.report import report_bp
from models.db import (Entity, Report, ReportCashCountDraft, ReportSaleDetail,
                       SaleInfo, ShopExpense, db)
from services.helpers.docx import convert_docx_to_pdf
from services.permission_policy import can_view_report


@report_bp.route("/report/<string:id>/export", methods=["GET"])
@login_required
def generate_pdf_report(id):
    try:
        query_result = (
            db.session.query(
                Report,
                Entity) .join(
                Entity,
                Entity.id.cast(
                    db.String) == Report.company,
                full=True) .filter(
                Report.id == id) .first())
        if query_result is None:
            return (
                jsonify({"status": "error", "message": "Hmm, I couldn't find that report."}),
                404,
            )
        report, entity = cast(tuple[Report, Entity], query_result)
        if not report or not entity:
            return (
                jsonify({"status": "error", "message": "Hmm, I couldn't find that report."}),
                404,
            )
        if not can_view_report(current_user, report):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to view this report.",
                    }
                ),
                403,
            )

        expenses = ShopExpense.query.filter_by(report_id=id).all()
        cash_count = ReportCashCountDraft.query.filter_by(report_id=id).first()
        if not cash_count:
            return (
                jsonify(
                    {"status": "error", "message": "I couldn't find a cash count for that report."}
                ),
                404,
            )

        entity_id = report.company
        sale_info_list = (
            SaleInfo.query.filter_by(entity_id=entity_id, enabled=True)
            .order_by(SaleInfo.display_order)
            .all()
        )

        report_sale_details = (
            db.session.query(ReportSaleDetail, SaleInfo)
            .join(SaleInfo, ReportSaleDetail.sale_id == SaleInfo.sale_id)
            .filter(ReportSaleDetail.report_id == id)
            .all()
        )

        sale_detail_amounts = {}
        for sale_detail, sale_info in report_sale_details:
            if sale_info.value_name:
                sale_detail_amounts[sale_info.value_name] = sale_detail.amount or 0

        template_path = os.path.join(
            app.root_path, "static", "doc", "Daily_Report_Template.docx"
        )
        if not os.path.exists(template_path):
            return (
                jsonify({"status": "error", "message": "Something's not set up right on my end — I'm missing the report template. Could you let us know?"}),
                500,
            )
        doc = DocxTemplate(template_path)

        shop_sales = {}
        for sale in sale_info_list:
            if sale.type in ["Electronic", "Cash"] and sale.value_name:
                if sale.value_name == "deliveroo_sales":
                    continue
                sale_value = sale_detail_amounts.get(sale.value_name)
                if sale_value is None:
                    sale_value = getattr(report, sale.value_name, 0) or 0
                key = (
                    sale.value_name.replace("_sales", "")
                    if sale.value_name.endswith("_sales")
                    else sale.value_name
                )
                shop_sales[key] = sale_value or 0
        if "cash" not in shop_sales:
            cash_value = sale_detail_amounts.get("cash_sales")
            if cash_value is None:
                cash_value = report.cash_sales if report.cash_sales else 0
            shop_sales["cash"] = cash_value or 0

        delivery_sales = {}
        for sale in sale_info_list:
            if sale.type == "Delivery" and sale.value_name:
                if sale.value_name == "deliveroo_sales":
                    continue
                sale_value = sale_detail_amounts.get(sale.value_name)
                if sale_value is None:
                    sale_value = getattr(report, sale.value_name, 0) or 0
                key = (
                    sale.value_name.replace("_sales", "")
                    if sale.value_name.endswith("_sales")
                    else sale.value_name
                )
                delivery_sales[key] = sale_value or 0

        data = {
            "company": entity.name if entity.name else "NA",
            "date": datetime.today().strftime("%Y-%m-%d"),
            "Prepared_by": report.uploaded_by if report.uploaded_by else "NA",
            "Approved_by": "NA",
            "shop_sales": shop_sales,
            "delivery_sales": delivery_sales,
            "expenses": [],
            "drawer_set1": {
                "1000": cash_count.thousand_note if cash_count.thousand_note else 0,
                "500": (
                    cash_count.fivehundred_note if cash_count.fivehundred_note else 0
                ),
                "100": cash_count.onehundred_note if cash_count.onehundred_note else 0,
                "50": cash_count.fifty_note if cash_count.fifty_note else 0,
                "20": cash_count.twenty_note if cash_count.twenty_note else 0,
            },
            "drawer_set2": {
                "10": cash_count.ten_note if cash_count.ten_note else 0,
                "5": cash_count.five_coin if cash_count.five_coin else 0,
                "2": cash_count.two_coin if cash_count.two_coin else 0,
                "1": cash_count.one_coin if cash_count.one_coin else 0,
            },
            "opening_balance": report.opening_balance if report.opening_balance else 0,
            "cash_withdrawal": report.cash_addition if report.cash_addition else 0,
            "bank_deposit": report.bank_deposit if report.bank_deposit else 0,
        }

        for expense in expenses:
            data["expenses"].append(
                {"item": expense.item, "amount": expense.amount})

        context = {
            "company": data["company"],
            "Date": data["date"],
            "Prepared_by": data["Prepared_by"],
            "Approved_by": data["Approved_by"],
        }

        shop = data["shop_sales"]
        cash_sales_value = shop.get("cash", 0)
        context["cash"] = cash_sales_value
        context["cash_sales"] = cash_sales_value
        context["Cash_Sales"] = cash_sales_value

        electronic_sales = [
            sale
            for sale in sale_info_list
            if sale.type == "Electronic"
            and sale.value_name
            and sale.value_name != "deliveroo_sales"
        ]
        for i in range(1, 21):
            context[f"option{i}_name"] = ""
            context[f"option{i}_sales"] = 0
        for i, sale in enumerate(electronic_sales[:20], start=1):
            key = (
                sale.value_name.replace("_sales", "")
                if sale.value_name.endswith("_sales")
                else sale.value_name
            )
            display_name = (
                sale.sale_name or sale.value_name.replace(
                    "_sales", "").replace(
                    "_", " ").title())
            context[f"option{i}_name"] = display_name
            context[f"option{i}_sales"] = shop.get(key, 0)
        context["shop_total"] = sum(shop.values())

        delivery = data["delivery_sales"]
        delivery_sales_list = [
            sale
            for sale in sale_info_list
            if sale.type == "Delivery"
            and sale.value_name
            and sale.value_name != "deliveroo_sales"
        ]
        for i in range(1, 11):
            context[f"delivery{i}_name"] = ""
            context[f"delivery{i}_sales"] = 0
        for i, sale in enumerate(delivery_sales_list[:10], start=1):
            key = (
                sale.value_name.replace("_sales", "")
                if sale.value_name.endswith("_sales")
                else sale.value_name
            )
            display_name = (
                sale.sale_name or sale.value_name.replace(
                    "_sales", "").replace(
                    "_", " ").title())
            if sale.value_name == "foodpanda_sales":
                display_name = "Food Panda"
            elif sale.value_name == "keeta_sales":
                display_name = "Keeta"
            elif sale.value_name == "openrice_sales":
                display_name = "OpenRice"
            context[f"delivery{i}_name"] = display_name
            context[f"delivery{i}_sales"] = delivery.get(key, 0)
        context["delivery_total"] = sum(delivery.values())

        total_expenses = 0
        for i, expense in enumerate(data.get("expenses", []), start=1):
            context[f"expense_item{i}_name"] = expense["item"]
            context[f"expense_item{i}_amount"] = expense["amount"]
            total_expenses += expense["amount"]
        context["expense_total"] = total_expenses
        context["expenses_balance"] = total_expenses

        drawer_total = 0
        for idx, drawer_set in enumerate(
            [data.get("drawer_set1", {}), data.get("drawer_set2", {})], start=1
        ):
            for denom, qty in drawer_set.items():
                amount = int(denom) * qty
                context[f"qty{idx}_{denom}"] = qty
                context[f"amt{idx}_{denom}"] = amount
                drawer_total += amount
        context["drawer_total"] = drawer_total

        opening_balance = data.get("opening_balance", 0)
        cash_addition = report.cash_addition if report.cash_addition else 0
        bank_deposit = data.get("bank_deposit", 0)
        cash_sales = context["Cash_Sales"]
        closing_balance = (
            opening_balance +
            cash_addition +
            cash_sales -
            total_expenses -
            bank_deposit)
        context.update(
            {
                "opening_balance": opening_balance,
                "cash_withdrawal": cash_addition,
                "cash_addition": cash_addition,
                "bank_deposit": bank_deposit,
                "closing_balance": closing_balance,
            }
        )

        doc.render(context)

        temp_dir = os.path.join(app.root_path, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        docx_filename = f"Daily_Report_{report.transaction_date}_{report.id}.docx"
        pdf_filename = f"Daily_Report_{report.transaction_date}_{report.id}.pdf"
        docx_path = os.path.join(temp_dir, docx_filename)
        pdf_path = os.path.join(temp_dir, pdf_filename)
        doc.save(docx_path)

        if not os.path.exists(docx_path):
            return (
                jsonify({"status": "error", "message": "Something went wrong on my end while building that document. Mind trying again?"}),
                500,
            )

        try:
            if convert_docx_to_pdf(docx_path, pdf_path):
                if not os.path.exists(pdf_path):
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "message": "Something went wrong on my end while building that PDF. Mind trying again?",
                            }
                        ),
                        500,
                    )

                logger.info(
                    f"Report generated successfully: DOCX={docx_path}, PDF={pdf_path}"
                )

                def delete_file_later(path):
                    time.sleep(5)
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                            logger.info(f"Screenshot file deleted: {path}")
                    except Exception as ex:
                        logger.error(f"Failed to delete screenshot file: {ex}")

                threading.Thread(
                    target=delete_file_later, args=(pdf_path,), daemon=True
                ).start()
                threading.Thread(
                    target=delete_file_later, args=(docx_path,), daemon=True
                ).start()
                return send_file(
                    pdf_path,
                    mimetype="application/pdf",
                    as_attachment=True,
                    download_name=pdf_filename,
                )
            else:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Something went wrong on my end while making that PDF. Mind trying again?",
                        }
                    ),
                    500,
                )
        except Exception as e:
            logger.error(f"Error converting DOCX to PDF: {str(e)}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Something went wrong on my end while making that PDF. Mind trying again?",
                    }),
                500,
            )
    except Exception as e:
        logger.error(f"Error generating report: {str(e)}")
        return (jsonify({"status": "error",
                         "message": "Something went wrong on my end while building that report. Mind trying again?",
                         }),
                500,
                )


@report_bp.route("/report/<string:id>/screenshot", methods=["GET"])
@login_required
def report_screenshot(id=None):
    from selenium import webdriver
    from selenium.webdriver.common.by import By

    try:
        report = Report.query.get_or_404(id)
        if not can_view_report(current_user, report):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "You do not have permission to view this report.",
                    }
                ),
                403,
            )
        ua_string = request.headers.get("User-Agent", "")
        user_agent = parse(ua_string)
        browser_name = user_agent.browser.family.lower()
        url = url_for("report.report_ending", id=id, _external=True)

        driver = None
        if "chrome" in browser_name:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-shm-usage")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-gpu")
            driver = webdriver.Chrome(options=chrome_options)
        elif "firefox" in browser_name:
            firefox_options = webdriver.FirefoxOptions()
            firefox_options.add_argument("--headless")
            firefox_options.add_argument("--window-size=1920,1080")
            driver = webdriver.Firefox(options=firefox_options)
        elif "edge" in browser_name:
            edge_options = webdriver.EdgeOptions()
            edge_options.add_argument("--headless")
            edge_options.add_argument("--window-size=1920,1080")
            driver = webdriver.Edge(options=edge_options)
        elif "safari" in browser_name:
            safari_options = webdriver.SafariOptions()
            safari_options.add_argument("--headless")
            driver = webdriver.Safari(options=safari_options)
        else:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Unsupported browser: {browser_name}",
                    }
                ),
                400,
            )

        driver.get(url)
        screenshots_dir = os.path.join(app.root_path, "temp", "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        filepath = os.path.join(
            screenshots_dir,
            f"Report_Ending_{report.transaction_date}_{report.id}.png",
        )
        driver.find_element(By.ID, "ending-content").screenshot(filepath)
        driver.quit()

        def delete_file_later(path):
            time.sleep(5)
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logger.info(f"Screenshot file deleted: {path}")
            except Exception as ex:
                logger.error(f"Failed to delete screenshot file: {ex}")

        threading.Thread(
            target=delete_file_later, args=(filepath,), daemon=True
        ).start()
        logger.info(f"Screenshot saved for {browser_name}")
        return send_file(
            filepath,
            mimetype="image/png",
            as_attachment=True,
            download_name=f"Report_Ending_{report.transaction_date}_{report.id}.png",
        )
    except Exception as e:
        # Screenshot generation failing is a server-side fault, not a missing
        # report — 404 misreported it as "not found".
        logger.exception(f"Error in getting report screenshot: {str(e)}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I couldn't open that report. Mind trying again?",
                }
            ),
            500,
        )
