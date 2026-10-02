"""The sidebar on this app's own pages - minty-web's one drawer with two views
(``minty-web/components/ui/Sidebar.tsx``), ported to Jinja on 2026-09-30 at the user's word:

* the MENU (Figma 02, minty-web's ``SideMenu.tsx``), opened by a header's ≡;
* MY PROFILE (Figma 10-A, minty-web's ``features/profile``), opened by the header's initials
  or from the menu by the person's name; its ‹ goes back to the menu.

The menu is drawn here, server-side (``templates/components/minty_sidebar.html``). My Profile
and its Subscriptions Overview are drawn in the browser (``static/js/minty_sidebar.js``) over
the SAME reads minty-web makes - this app's ``GET``/``PATCH /api/me/profile`` and
minty-billing-api's ``GET /api/me/subscriptions`` - with the bearer token
``GET /me/sidebar-token`` hands the page.

A PORT, not a copy to be lifted: ``@minty/shared`` is TypeScript and cannot serve Jinja, so
this retires with these pages when they move to Next (Part 3). Until then a change to
minty-web's menu or profile is a change here too (the same words, sizes and colours).

This module is the one place that decides WHAT the menu holds on a page and WHERE each item
goes; the template only draws it. Whether a module's group is on is the context processor's
``is_petty_cash_enabled`` / ``is_billing_enabled`` (``pettycash/core/hooks.py``), read in the
template because the module settings page shows and hides those groups live
(``data-module-nav``).
"""

from __future__ import annotations

from flask import request, url_for
from flask_login import current_user
from loguru import logger

from blueprints.user_management.services import profile
from services.app_runtime.env import url_env

#: Where minty-subscription-api answers (the Subscriptions Overview's read) - the same
#: ``SUBSCRIPTION_API_URL`` minty-web reads.
SUBSCRIPTION_API_URL_DEFAULT = "http://localhost:8000"

#: Pages where a person is CHOOSING a company rather than inside one: no company sections and
#: no Settings there, whatever the page was handed (minty-web: never on the entity list).
CHOOSING_ENDPOINTS = frozenset(
    {
        "entity.entity_list",
        "entity.entity_create",
        "entity.entity_create_success",
        "entity_list",
        "entity_create",
        "entity_create_success",
    }
)

#: minty-web's pages the menu leads to, through ``/handoff/minty-web`` (which mints the token).
MINTY_WEB_SUBSCRIPTIONS_PATH = "/subscription"


def subscription_api_origin() -> str:
    """minty-subscription-api's origin, without a trailing slash (the browser compares it
    literally)."""
    return url_env("SUBSCRIPTION_API_URL", SUBSCRIPTION_API_URL_DEFAULT)


def _petty_cash_on(entity_id: str) -> bool:
    """Whether Petty Cash is on for the company - the module gate's own read. An unreadable
    answer counts as ON, and is logged: the context processor's rule for the menu's module
    groups (``pettycash/core/hooks.py``), so a transient hiccup never hides the way in."""
    from blueprints.entity.routes.modules import _is_module_enabled

    try:
        return _is_module_enabled(entity_id, "PETTY_CASH")
    except Exception:
        logger.exception(f"sidebar: the Petty Cash lookup failed for entity {entity_id}")
        return True


def _settings(company: str, from_bills: bool) -> tuple[str, str]:
    """``(href, endpoint)`` of the Settings item: the settings of THE APP it is pressed in (the
    user's call, 2026-09-30 - minty-web's menu keeps its module page).

    * The Payment Request pages (``?from=bills``): the payments app's Payment Settings, through
      the route that mints its token at the click - where billing-frontend's own Settings goes.
    * Everywhere else, Petty Cash: its Petty Cash Settings tab, where the accounts and contacts a
      report needs are set (the dashboard's "Setup Required" lists exactly those). A company
      without Petty Cash has no such tab (``require_module``), so it gets Entity & Integration.
    """
    if from_bills:
        endpoint = "entity.entity_settings_payments"
        return url_for(endpoint, org_id=company, **{"from": "bills"}), endpoint
    if _petty_cash_on(company):
        endpoint = "entity.entity_settings_entity"
        return url_for(endpoint, org_id=company), endpoint
    endpoint = "entity.entity_settings"
    return url_for(endpoint, entity_id=company), endpoint


def _current(endpoint: str, settings_endpoint: str | None) -> str | None:
    """Which menu item is the page being shown - marked for assistive technology only
    (``aria-current``); the design draws the current item like any other."""
    if endpoint in ("entity.entity_list", "entity_list"):
        return "entities"
    if endpoint == "entity.report_dashboard":
        return "dashboard"
    if endpoint.startswith("report."):
        return "reports"
    if settings_endpoint and endpoint == settings_endpoint:
        return "settings"
    return None


def sidebar_context(entity_id=None, *, from_bills: bool = False) -> dict:
    """Everything ``components/minty_sidebar.html`` draws, for the page being rendered.

    ``entity_id`` is the company the page is about (the template's ``org.id`` or
    ``entity_id``); ``from_bills`` marks the Payment Request settings pages, whose Settings and
    profile keep ``?from=bills`` so the way back leads to the payments app.
    """
    endpoint = request.endpoint or ""
    company = str(entity_id) if entity_id and endpoint not in CHOOSING_ENDPOINTS else ""
    bills = {"from": "bills"} if from_bills else {}

    settings_endpoint = None
    links = {
        "entities": url_for("entity.entity_list"),
        "subscriptions": url_for("entity.handoff_minty_web", next=MINTY_WEB_SUBSCRIPTIONS_PATH),
        "logout": url_for("auth.logout"),
        # the initials' href when scripts are off: the profile router, as before
        "profile": url_for("entity.open_profile", **({"entity_id": company} if company else {}), **bills),
    }
    if company:
        links["settings"], settings_endpoint = _settings(company, from_bills)
        links.update(
            {
                "dashboard": url_for("entity.report_dashboard", id=company),
                "reports": url_for("report.entity_report_history", entity_id=company),
                "bills": url_for("entity.go_to_bills", entity_id=company),
            }
        )

    # Every page that draws the sidebar is signed-in only; a render without a person (a
    # template rendered on its own) draws an empty name rather than failing.
    signed_in = current_user.is_authenticated
    return {
        "entity_id": company,
        "in_company": bool(company),
        "current": _current(endpoint, settings_endpoint),
        "viewer": {
            "name": profile.display_name(current_user) if signed_in else "",
            "initials": profile.initials(current_user) if signed_in else "",
        },
        "links": links,
        "api": {
            "token": url_for("entity.sidebar_token"),
            "profile": url_for("user_management.my_profile_api"),
            "billing": subscription_api_origin(),
        },
    }
