# Plan

`docs/ko/user_permission_matrix_explain.md` 요구사항을 코드에 반영하기 위해 권한 정책을 중앙화하고, 고위험 라우트부터 단계적으로 적용한다. 먼저 공통 `permission policy + authz decorator`를 추가한 뒤, 사용자/엔티티/Xero/리포트 핵심 경로에 적용하고 테스트로 검증한다.

## Scope
- In:
  - 권한 정책 모듈 및 데코레이터 신설
  - 사용자 생성 API, 엔티티 설정, 결제수단 API, Xero 핵심 API, 리포트 핵심 경로 권한 적용
  - 최소 단위 테스트 추가 및 실행
- Out:
  - 전체 라우트(88개) 일괄 권한 전환
  - UI/템플릿 권한 표시 리디자인
  - 대규모 DB 스키마 변경(soft delete 컬럼 추가 등)

## Action items
[x] Add centralized permission policy in `services/permission_policy.py`
[x] Add reusable authz decorators in `services/authz.py`
[x] Protect user creation and payment-method APIs with permission checks
[x] Apply entity/Xero route permission checks for critical settings and data endpoints
[x] Apply report route permission checks for history/edit/delete and align entity creator role assignment
[x] Add unit tests for permission policy behavior
[x] Run test suite and fix regressions (new tests pass, full suite blocked by missing `loguru` in local test env)
[x] Mark this plan checklist complete and commit all related changes

## Open questions
- `docs/ko/user_permission_matrix_new_required.md` 원본 부재 상태에서 TBD 항목을 어떻게 확정할지
- `entity_base` 사용자의 첫 엔티티 생성 허용 정책을 장기적으로 유지할지
- 사용자 삭제 정책을 soft delete로 전환할지(현 단계는 범위 제외)

## Checklist (Current round)
[x] Add explicit `ENTITY_CREATE` permission and guard `/entity/create`
[x] Guard Xero publish endpoint with entity-scoped permission (`Accountant+`)
[x] Restrict report publishing status API to matrix-aligned role (`Shop Manager+`)
[x] Protect Xero sync-status API with login + entity access + permission
[x] Add/adjust unit tests for the new permission paths
[x] Run targeted pytest suite for permission/authz tests

## Checklist (Gap-closing round 2)
[x] Add `Report History` own-view fallback for Cashier while keeping entity-wide view at `Shop Manager+`
[x] Guard Xero connect/refresh entry points that were still weakly protected
[x] Add `Entity delete` endpoint with permission gate (`Admin+`) and soft-delete behavior
[x] Add user role management APIs for role update/delete with matrix-aligned permission checks
[x] Add self-account deactivation endpoint (data-preserving)
[x] Add/adjust permission tests for the new policy surface
[x] Run targeted pytest for updated permission/authz tests

## Checklist (Gap-closing round 3)
[x] Harden `Report Daily` views/APIs with entity-context permission checks (own/entity rules)
[x] Tighten report export/download and submitted/detail access to prevent cross-user leakage
[x] Protect Xero helper routes (`remove/connections/all`, `debug/xero-settings`) with entity-scoped permission
[x] Add self-profile update endpoint for user own-info update scenario
[x] Expand permission tests for newly hardened routes/policy behavior
[x] Run targeted pytest for permission/authz regression

## Checklist (Gap-closing round 4)
[x] Add strict report-id access guards on daily step routes (`opening/sales/expense/deposit/cash_count`)
[x] Add strict report-id access guard in ending service flow
[x] Verify report-id paths enforce owner-or-entity-editor policy consistently
[x] Add/adjust unit tests for report access guard behavior
[x] Run targeted pytest and close remaining checklist

## Checklist (Gap-closing round 5)
[x] Guard `/report/<id>/export` with report view policy (`owner or entity viewer`)
[x] Guard `/report/<id>/screenshot` with login + report view policy
[x] Align `convert-to-draft` permission with report edit policy (`owner or entity editor`)
[x] Re-run targeted permission/authz tests

## Checklist (권한 매트릭스 점검 2026-03-10)
- [x] 사용자 생성(본인 계정): `/register` 회원가입 플로우 동작
- [x] 사용자 초대: `POST /minty/api/users/create` requires `Permission.USER_INVITE` (`Shop Manager+`)
- [x] 사용자 조회(개인): `GET /minty/api/users/me` 허용
- [x] 사용자 조회(전체): `GET /entity/settings/users/<org_id>` requires `Permission.USER_VIEW_ALL` (`Shop Manager+`)
- [x] 사용자 수정(개인정보): `PATCH /minty/api/users/me` 허용
- [x] 사용자 역할 설정/변경: `PATCH /minty/api/users/<user_id>/role` requires `Permission.USER_ROLE_ASSIGN` + actor/rank 제어
- [x] 사용자 역할 정보 조회: `GET /entity/settings/users/<org_id>` 노출
- [x] 사용자 삭제(본인계정): `DELETE /minty/api/users/me` 수행
- [x] 사용자 역할 삭제: `DELETE /minty/api/users/<user_id>/role` requires `Permission.USER_ROLE_DELETE` (`Accountant+`)
- [x] 엔티티 생성: `GET/POST /entity/create` requires `Permission.ENTITY_CREATE` (`Accountant+`)
- [x] 엔티티 조회: `/entity/<id>`에서 멤버십/`Permission.ENTITY_VIEW`로 제한
- [x] 엔티티 수정: `/entity/settings/entity/<org_id>`에서 `ENTITY_UPDATE`/`COA_*` 동작 제어 적용
- [x] 엔티티 삭제: `POST /entity/<id>/delete` requires `Permission.ENTITY_DELETE` (`Admin+`)
- [x] Sales Method 생성: `POST /api/entities/<entity_id>/payment-methods` requires `Permission.SALES_METHOD_CREATE` (`Accountant+`)
- [x] Sales Method 조회: `GET /api/entities/<entity_id>/payment-methods` requires `Permission.SALES_METHOD_VIEW` (`Cashier+`)
- [x] Sales Method 수정: `PUT /api/entities/<entity_id>/payment-methods/<method_id>` requires `Permission.SALES_METHOD_UPDATE` (`Accountant+`)
- [x] Sales Method 삭제: `DELETE /api/entities/<entity_id>/payment-methods/<method_id>` requires `Permission.SALES_METHOD_DELETE` (`Accountant+`)
- [x] Sales Method 재정렬: `PUT /api/entities/<entity_id>/payment-methods/reorder` requires `Permission.SALES_METHOD_REORDER` (`Accountant+`)
- [x] CoA 조회: `Permission.COA_VIEW` 적용 (`Cashier+`)
- [x] CoA 생성/수정/삭제: `COA_CREATE`/`COA_UPDATE`/`COA_DELETE` 적용 (`Accountant+`)
- [x] 리포트 작성: 일일 작성/단계 API에서 `Permission.REPORT_EDIT_OWN` 또는 `REPORT_EDIT_ENTITY`로 제한
- [x] 리포트 조회(내 작성): 업로더 + `REPORT_VIEW_OWN` 허용
- [x] 리포트 조회(엔티티): `Permission.REPORT_VIEW_ENTITY` (`Shop Manager+`) 적용
- [x] 리포트 수정: `can_edit_report` 로직에서 업로더/엔티티 편집 권한 반영
- [x] 리포트 삭제(내 작성): 업로더 + `REPORT_DELETE_OWN` 허용
- [x] 리포트 삭제(엔티티): `Permission.REPORT_DELETE_ENTITY` 적용 (`Shop Manager+`)
- [x] Report History 조회(내 작성): `REPORT_VIEW_OWN`로 허용
- [x] Report History 조회(엔티티): `Permission.REPORT_VIEW_ENTITY`로 허용
- [x] Xero 연동 생성: `/xero_connect`는 `Permission.ENTITY_CREATE` 기반
- [x] Xero 설정 페이지/조회: `XERO_SETTINGS_VIEW` (`Cashier+`) 및 업데이트 경로에 `XERO_SETTINGS_UPDATE` 적용
- [x] Xero 게시 생성: `/report/submitted/publish_to_xero` requires `Permission.REPORT_PUBLISH` (`Accountant+`)
- [x] Xero 게시 조회: `GET /api/report/<report_id>/publishing_status` requires `Permission.REPORT_VIEW_ENTITY` (`Shop Manager+`)
- [x] Xero 재게시/삭제: 재게시는 내부 처리로 수용, 삭제 API는 매트릭스 미제공 상태 유지
- [x] 미구현 항목 없음: 현재 문서 기준 모든 항목 구현 완료
