# Manual Redirect Access Denials

Date: 2026-03-12
Branch: `refactoring_david`

## Scope

This document covers the `22` route-level cases where permission or access denial is handled manually with `flash(...) + redirect(...)`.

These cases do **not** go through the new `auth.no_permission` / `entity_no_permission.html` fallback.

Excluded from this document:
- decorator-based denials handled by `@require_permission` or `@require_entity_access`
- JSON `403` responses in API routes
- non-permission redirects such as `Entity context is required`, `Report not found`, or `You need to create an entity first`

## Permission Meaning

- `ENTITY_VIEW`: entity-scoped, minimum role `cashier`
- `ENTITY_CREATE`: non-entity-scoped, allowed for authenticated users (`normal` / `superuser`)
- `ENTITY_UPDATE`: entity-scoped, minimum role `accountant`
- `COA_CREATE` / `COA_UPDATE` / `COA_DELETE`: entity-scoped, minimum role `accountant`
- `XERO_SETTINGS_UPDATE`: entity-scoped, minimum role `accountant`
- `REPORT_EDIT_OWN`: entity-scoped, minimum role `cashier`
- `REPORT_EDIT_ENTITY`: entity-scoped, minimum role `shop_manager`
- `REPORT_DELETE_OWN`: entity-scoped, minimum role `cashier`
- `REPORT_DELETE_ENTITY`: entity-scoped, minimum role `shop_manager`

Notes:
- `has_permission(...)` for entity-scoped permissions also requires approved entity membership.
- `can_edit_report(...)` means:
  - allowed when the current user is the uploader and has `REPORT_EDIT_OWN`, or
  - allowed when the user has `REPORT_EDIT_ENTITY`
- `can_delete_report(...)` means:
  - allowed when the current user is the uploader and has `REPORT_DELETE_OWN`, or
  - allowed when the user has `REPORT_DELETE_ENTITY`

## Detailed Cases

| # | Location | Current check | When the redirect happens | What permission/access is missing | Current redirect | Fallback that should be shown |
|---|---|---|---|---|---|---|
| 1 | `blueprints/entity/routes/list.py:62` `report_dashboard(id)` | `if not user_entity` | User opens an entity dashboard for an entity where there is no `UserEntity` membership row for that user | Entity membership / entity access itself is missing | `entity.entity_list` | `auth.no_permission?entity_id=<id>` |
| 2 | `blueprints/entity/routes/list.py:65` `report_dashboard(id)` | `if not has_permission(..., ENTITY_VIEW, id)` | User has a membership row but still cannot view the entity dashboard | `ENTITY_VIEW` is missing; in practice this means approved access is missing or the effective role is below `cashier` | `entity.entity_list` | `auth.no_permission?entity_id=<id>` |
| 3 | `blueprints/entity/routes/settings.py:72` `entity_settings(entity_id)` `POST` | `if not has_permission(..., XERO_SETTINGS_UPDATE, entity_id)` | User can open the Xero settings page, but submits a save/update action without update rights | `XERO_SETTINGS_UPDATE` is missing; minimum role is `accountant` | `entity_settings(entity_id)` | `auth.no_permission?entity_id=<entity_id>` |
| 4 | `blueprints/entity/routes/settings.py:1293` `entity_settings_entity(org_id)` `POST` | `if not has_permission(..., ENTITY_UPDATE, org_id)` | User submits entity settings changes without entity update rights | `ENTITY_UPDATE` is missing; minimum role is `accountant` | `entity_settings_entity(org_id)` | `auth.no_permission?entity_id=<org_id>` |
| 5 | `blueprints/entity/routes/settings.py:1296` `entity_settings_entity(org_id)` `POST` | `if not has_permission(..., COA_UPDATE, org_id)` | User submits CoA-related changes that update existing CoA settings/accounts | `COA_UPDATE` is missing; minimum role is `accountant` | `entity_settings_entity(org_id)` | `auth.no_permission?entity_id=<org_id>` |
| 6 | `blueprints/entity/routes/settings.py:1299` `entity_settings_entity(org_id)` `POST` | `if not has_permission(..., COA_CREATE, org_id)` | User submits CoA-related changes that create new CoA settings/accounts | `COA_CREATE` is missing; minimum role is `accountant` | `entity_settings_entity(org_id)` | `auth.no_permission?entity_id=<org_id>` |
| 7 | `blueprints/entity/routes/settings.py:1302` `entity_settings_entity(org_id)` `POST` | `if not has_permission(..., COA_DELETE, org_id)` | User submits CoA-related changes that delete CoA settings/accounts | `COA_DELETE` is missing; minimum role is `accountant` | `entity_settings_entity(org_id)` | `auth.no_permission?entity_id=<org_id>` |
| 8 | `blueprints/xero/routes/routes.py:51` `xero_connect_entity()` | `if not has_permission(..., ENTITY_CREATE)` | User starts the "connect new entity to Xero" flow without entity creation rights | `ENTITY_CREATE` is missing; this is a system-level authenticated-user permission and not entity-scoped | `entity.entity_list` | Generic `auth.no_permission` page |
| 9 | `blueprints/report/routes/create.py:26` `create_report()` | `if not has_permission(..., REPORT_EDIT_OWN, entity_id)` | User tries to create a report for the company bound to their account but lacks report creation/edit rights there | `REPORT_EDIT_OWN` is missing; minimum role is `cashier` with approved entity access | `auth.index` | `auth.no_permission?entity_id=<current_user.company>` |
| 10 | `blueprints/report/routes/opening.py:39` `report_opening(...)` | `if not has_permission(..., REPORT_EDIT_OWN, entity_id)` | User enters the opening step for an entity where they cannot create/edit their own report | `REPORT_EDIT_OWN` is missing; minimum role is `cashier` with approved entity access | `entity.entity_list` | `auth.no_permission?entity_id=<entity_id>` |
| 11 | `blueprints/report/routes/opening.py:49` `report_opening(...)` | `if not can_edit_report(current_user, report_for_access)` | User opens an existing report/draft in the opening step but is not allowed to edit that specific report | Usually the report was uploaded by someone else and the user lacks `REPORT_EDIT_ENTITY`; entity-level edit requires at least `shop_manager` | `entity.report_dashboard(id=entity_id)` | `auth.no_permission?entity_id=<entity_id>` |
| 12 | `blueprints/report/routes/sales.py:31` `report_sale(...)` | `if not has_permission(..., REPORT_EDIT_OWN, entity_id)` | User enters the sales step for an entity where they cannot create/edit their own report | `REPORT_EDIT_OWN` is missing; minimum role is `cashier` with approved entity access | `entity.entity_list` | `auth.no_permission?entity_id=<entity_id>` |
| 13 | `blueprints/report/routes/sales.py:41` `report_sale(...)` | `if not can_edit_report(current_user, report_for_access)` | User opens an existing report/draft in the sales step but is not allowed to edit that specific report | Usually the report was uploaded by someone else and the user lacks `REPORT_EDIT_ENTITY`; entity-level edit requires at least `shop_manager` | `entity.report_dashboard(id=entity_id)` | `auth.no_permission?entity_id=<entity_id>` |
| 14 | `blueprints/report/routes/expense.py:39` `report_expense(...)` | `if not has_permission(..., REPORT_EDIT_OWN, entity_id)` | User enters the expense step for an entity where they cannot create/edit their own report | `REPORT_EDIT_OWN` is missing; minimum role is `cashier` with approved entity access | `entity.entity_list` | `auth.no_permission?entity_id=<entity_id>` |
| 15 | `blueprints/report/routes/expense.py:49` `report_expense(...)` | `if not can_edit_report(current_user, report_for_access)` | User opens an existing report/draft in the expense step but is not allowed to edit that specific report | Usually the report was uploaded by someone else and the user lacks `REPORT_EDIT_ENTITY`; entity-level edit requires at least `shop_manager` | `entity.report_dashboard(id=entity_id)` | `auth.no_permission?entity_id=<entity_id>` |
| 16 | `blueprints/report/routes/deposit.py:33` `report_deposit(...)` | `if not has_permission(..., REPORT_EDIT_OWN, entity_id)` | User enters the deposit step for an entity where they cannot create/edit their own report | `REPORT_EDIT_OWN` is missing; minimum role is `cashier` with approved entity access | `entity.entity_list` | `auth.no_permission?entity_id=<entity_id>` |
| 17 | `blueprints/report/routes/deposit.py:43` `report_deposit(...)` | `if not can_edit_report(current_user, report_for_access)` | User opens an existing report/draft in the deposit step but is not allowed to edit that specific report | Usually the report was uploaded by someone else and the user lacks `REPORT_EDIT_ENTITY`; entity-level edit requires at least `shop_manager` | `entity.report_dashboard(id=entity_id)` | `auth.no_permission?entity_id=<entity_id>` |
| 18 | `blueprints/report/routes/cash_count.py:28` `report_cash_count(...)` | `if not has_permission(..., REPORT_EDIT_OWN, entity_id)` | User enters the cash count step for an entity where they cannot create/edit their own report | `REPORT_EDIT_OWN` is missing; minimum role is `cashier` with approved entity access | `entity.entity_list` | `auth.no_permission?entity_id=<entity_id>` |
| 19 | `blueprints/report/routes/cash_count.py:38` `report_cash_count(...)` | `if not can_edit_report(current_user, report_for_access)` | User opens an existing report/draft in the cash count step but is not allowed to edit that specific report | Usually the report was uploaded by someone else and the user lacks `REPORT_EDIT_ENTITY`; entity-level edit requires at least `shop_manager` | `entity.report_dashboard(id=entity_id)` | `auth.no_permission?entity_id=<entity_id>` |
| 20 | `blueprints/report/routes/report_detail.py:167` `edit_report(id)` | `if not can_edit_report(current_user, report)` | User opens the report edit screen for a report they are not allowed to edit | Own report edit needs `REPORT_EDIT_OWN`; editing another user's report needs `REPORT_EDIT_ENTITY` | `auth.index` or `index` | `auth.no_permission?entity_id=<report.company>` |
| 21 | `blueprints/report/routes/report_detail.py:391` `delete_report(id)` draft branch | `if not can_delete_report(current_user, report_draft)` | User tries to delete a draft they are not allowed to delete | Own draft delete needs `REPORT_DELETE_OWN`; deleting another user's draft needs `REPORT_DELETE_ENTITY` | `entity.report_dashboard(id=report_draft.company)` | `auth.no_permission?entity_id=<report_draft.company>` |
| 22 | `blueprints/report/routes/report_detail.py:406` `delete_report(id)` submitted report branch | `if not can_delete_report(current_user, report)` | User tries to delete a submitted report they are not allowed to delete | Own report delete needs `REPORT_DELETE_OWN`; deleting another user's report needs `REPORT_DELETE_ENTITY` | `entity.report_dashboard(id=report.company)` | `auth.no_permission?entity_id=<report.company>` |

## Observations

- Most of these are entity-scoped denials, so they can consistently show `auth.no_permission` with `entity_id`.
- The repeated report wizard routes follow the same two-pattern structure:
  - entity-level permission to start editing a report for that entity
  - object-level permission to edit a specific existing report/draft
- `entity_settings(entity_id)` is a particularly visible mismatch because the page is viewable with `XERO_SETTINGS_VIEW`, but saving requires `XERO_SETTINGS_UPDATE`.
- `xero_connect_entity()` is the only listed case that is not naturally tied to an existing entity context.
- In `entity_settings_entity(org_id)`, the four checks are sequential; in practice a lower-role user will usually fail the first accountant-level check before reaching the later ones.

## Suggested Use

When standardizing fallback behavior, these `22` manual cases are the first route-level places to replace with a shared no-permission response helper.
