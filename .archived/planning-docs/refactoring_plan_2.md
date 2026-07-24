# Plan

`User.company`를 더 이상 현재 엔티티 컨텍스트나 기본 작업 대상처럼 사용하지 않도록 제거한다. 접근 방식은 `UserEntity`를 권한 source of truth로 유지한 채, 엔티티 관련 화면과 API가 `entity_id`를 명시적으로 받도록 바꾸고 마지막에 `User.company` 컬럼을 삭제하는 것이다.

## Scope
- In: `User.company` 읽기/쓰기 제거, 엔티티 컨텍스트를 `entity_id` 기반으로 전환, 회원가입/프로필/조회 흐름에서의 `company` 의미 재정의, 관련 뷰/템플릿/API/테스트/마이그레이션 정리
- Out: 새로운 admin 기능 추가, 엔티티 권한 모델 자체 재설계, 전체 UX 리디자인

## Order assessment
- Start with contract and inventory before runtime edits because the current repo overloads `User.company` as profile text, default entity context, and membership cleanup state.
- Registration/profile/find-user changes are the safest first runtime slice after documentation because they do not own report persistence and have focused tests.
- Report, Xero, template navigation, and migration work should stay later because they have the widest blast radius and the highest redirect/context regression risk.
- Drop the DB column last, only after every route, template, API, and test passes without reading or writing `user.company`.

## Likely touch points
- Routes: `blueprints/auth/routes/dashboard.py`, `blueprints/auth/routes/login.py`, `blueprints/auth/routes/permissions.py`, `blueprints/entity/routes/create.py`, `blueprints/entity/routes/settings.py`, `blueprints/report/routes/create.py`, `opening.py`, `sales.py`, `expense.py`, `deposit.py`, `cash_count.py`, `report_detail.py`, `api.py`, `blueprints/report/services/ending.py`, `blueprints/xero/routes/routes.py`, `blueprints/xero/routes/settings.py`, `blueprints/user_management/routes/find_user.py`, `create_user.py`, `roles.py`.
- Templates: `templates/components/sidepanel.html`, `templates/index.html`, `templates/index2.html`, `templates/report/submitted.html`, `templates/admin_dashboard.html`, `templates/user approval.html`, `templates/find_user.html`, `templates/register.html`.
- APIs/contracts: `/minty/api/users/me`, `/minty/api/users/create`, `/minty/api/users/<user_id>/role`, and report draft/report submit APIs that still infer entity context from `current_user.company`.
- Persistence/tests: `blueprints/auth/models/user.py`, a new Alembic migration, plus tests that currently seed or assert `User.company`.

## Key risks
- Multi-entity users can land on the wrong dashboard if any redirect keeps assuming an implicit active entity.
- Report create/edit routes can silently read or write the wrong entity if even one fallback to `current_user.company` survives.
- Sidepanel and report links can regress into missing `entity_id` query params, producing 400/403 loops instead of usable navigation.
- Registration and user lookup can break if the `User.company` column is removed before those forms and tests stop depending on it.
- The final migration is destructive and must remain the last step.

## Action items
[x] `User.company`의 역할을 최종 고정한다: 전역/권한 필드로는 사용하지 않고, 엔티티 컨텍스트는 URL·폼·API의 `entity_id`로만 받는다. 세션 `active_entity_id`는 도입하지 않고, `/index`는 엔티티 미선택 시 `entity_list`로 보낸다.
[x] `User.company` 의존 지점을 전수 분류한다: `blueprints/auth/routes/dashboard.py`, `blueprints/auth/routes/register.py`, `blueprints/entity/routes/settings.py`, `blueprints/report/routes/create.py`, `report_detail.py`, `api.py`, `blueprints/report/services/ending.py`, `blueprints/xero/routes/settings.py`, `blueprints/xero/routes/routes.py`, `blueprints/auth/routes/permissions.py`, `blueprints/user_management/routes/find_user.py`, `roles.py`, `templates/components/sidepanel.html`, `templates/index.html`, `templates/index2.html`, `templates/report/submitted.html`, `templates/admin_dashboard.html`, `templates/user approval.html`에서 읽기/쓰기를 목록화한다.
[x] 회원가입과 사용자 조회에서 `company`가 맡는 도메인 의미를 분리한다: `blueprints/auth/forms.py`, `blueprints/auth/routes/register.py`, `templates/register.html`, `blueprints/user_management/forms.py`, `blueprints/user_management/routes/find_user.py` 기준으로 회원가입 `company` 입력은 제거하고, 사용자 조회는 membership 기반 엔티티 선택으로 전환한다.
[x] 엔티티 선택 흐름을 정리한다: `/index`와 리포트 작성 플로우가 암묵적 `current_user.company` 대신 명시적 `entity_id`를 요구하거나, 엔티티가 없으면 `entity_list`로 보내도록 라우트 계약을 바꾼다.
[x] Entity 생성·사용자 생성·멤버십 변경·Xero 연결에서 `User.company` 쓰기를 제거한다: `blueprints/entity/routes/create.py`, `blueprints/user_management/routes/create_user.py`, `blueprints/user_management/routes/roles.py`, `blueprints/xero/routes/routes.py`에서 `company` 대입·초기화 로직을 없애고 membership과 명시적 `entity_id`만 유지한다.
[x] 리포트·Xero·권한·엔티티 설정 화면을 `entity_id` 기반으로 바꾼다: `blueprints/report/routes/create.py`, `opening.py`, `sales.py`, `expense.py`, `deposit.py`, `cash_count.py`, `report_detail.py`, `api.py`, `blueprints/report/services/ending.py`, `blueprints/xero/routes/settings.py`, `blueprints/auth/routes/permissions.py`, `blueprints/entity/routes/settings.py`가 현재 엔티티를 요청값으로만 해석하도록 리팩터링한다.
[x] 템플릿과 admin 화면을 정리한다: `templates/components/sidepanel.html`, `templates/index.html`, `templates/index2.html`, `templates/report/submitted.html`, `templates/admin_dashboard.html`, `templates/user approval.html`에서 `current_user.company` 또는 `user.company` 가정을 제거하고, 필요한 `entity_id`와 membership 정보를 뷰에서 명시적으로 내려주도록 맞춘다.
[x] 프로필/API/조회 계약을 갱신한다: `/minty/api/users/me`에서 `company` 필드를 제거하거나 deprecated 처리하고, `find_user` 및 관련 응답이 `User.company`가 아니라 membership 또는 별도 프로필 필드를 기준으로 동작하도록 바꾼다.
[x] DB 전환을 수행한다: `blueprints/auth/models/user.py`와 Alembic migration에서 `User.company` 컬럼을 제거하고, 만약 회원가입의 회사명 정보가 필요하다면 대체 컬럼/모델로 백필한 뒤 one-shot 배포 기준의 백업·검증 쿼리·롤백 절차를 문서화한다.
[x] 테스트를 보강한다: `tests/test_entity_create.py`, `tests/test_user_profile_contract.py`, `tests/test_user_management_membership_roles.py`, 리포트 작성/조회 테스트, 사이드패널 링크 테스트, 회원가입/사용자 조회 테스트가 `User.company` 없이 동작하는지 단위·통합 테스트를 추가하고 기존 기대값을 갱신한다.
[x] 운영 리스크를 검증한다: 다중 엔티티 사용자의 기본 진입 화면, 엔티티 미선택 상태의 리다이렉트, 회원가입 이후 초기 진입 경로, 직접 URL 접근 시 권한/컨텍스트 불일치를 수동 시나리오로 확인한다.

## Validation log
- 2026-03-16: `python -m pytest tests/test_entity_selection_flow.py tests/test_entity_context_routes.py tests/test_user_profile_contract.py tests/test_find_user_membership_lookup.py tests/test_user_management_membership_roles.py tests/test_xero_company_writes.py` 기준 `36 passed`.
- 엔티티 미선택 진입과 직접 URL 접근은 `tests/test_entity_selection_flow.py`, `tests/test_entity_context_routes.py`, `tests/test_authz_decorators.py`로 검증했다.
- 회원가입 초기 진입과 `User.company` 제거 영향은 `tests/test_auth_register_login.py`, `tests/test_entity_create.py`에 기대값을 반영했다. 해당 Flask client 계열 통합 테스트는 별도 teardown instability가 있어 targeted validation 범위에서는 제외했다.
- 프로필/조회 계약과 membership 기반 조회는 `tests/test_user_profile_contract.py`, `tests/test_find_user_membership_lookup.py`, `tests/test_user_management_membership_roles.py`로 검증했다.

## Open questions
- None at this stage.
