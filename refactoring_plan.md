# Plan

`User.role`의 모호한 전역 역할을 `User.system_role`(`normal`, `superuser`)로 축소하고, 엔티티 권한의 source of truth는 계속 `UserEntity.role`로 유지한다. 이번 리팩터링은 정책 결정을 더 미루지 않고, `ENTITY_CREATE`, creator bootstrap role, `superuser` override, `User.role` 일괄 제거를 고정 전제로 구현하는 것이 목표다.

## Scope
- In: `User.role` -> `User.system_role` 전환, 전역 admin 접근 경로 정리, 권한 정책 단순화, API/템플릿/테스트/문서 갱신, 데이터 마이그레이션 설계
- Out: 새로운 admin UI 기능 추가, 엔티티별 역할 체계 자체 재설계, unrelated app 구조 리팩터링

## Fixed decisions
- `ENTITY_CREATE`는 모든 인증된 `normal` 사용자가 가능하도록 변경한다.
- 새 Entity를 만든 사용자는 해당 Entity의 `admin` membership을 즉시 부여받는다.
- `superuser`는 membership 없이 모든 엔티티에 접근 가능한 system-level override를 유지한다.
- `User.role`은 dual-read/double-write 없이 한 번에 제거하고 `User.system_role`로 치환한다.

## Action items
[x] `User.system_role` 계약을 코드와 문서에 고정한다: 허용값은 `normal`, `superuser`, 기본값은 `normal`, legacy `role` 매핑 규칙은 `admin`/`super_admin` -> `superuser`, 그 외는 `normal`으로 정리한다.
[x] DB 전환을 한 번에 수행한다: `blueprints/auth/models/user.py`와 Alembic migration에서 `User.role`을 `User.system_role`로 치환하고, 기존 데이터 backfill과 컬럼 제거를 같은 배포 단위로 묶는다.
[x] 권한 정책을 분리한다: `services/permission_policy.py`에서 entity-scoped 권한의 global role fallback을 제거하고, `superuser`만 membership 없이 모든 엔티티에 접근 가능한 override로 남긴다.
[x] `ENTITY_CREATE` 경로를 normal 기준으로 재정의한다: `blueprints/entity/routes/create.py`와 `blueprints/xero/routes/routes.py`가 모든 인증된 일반 사용자를 허용하도록 바꾸고, Entity 생성 직후 creator의 `UserEntity.role`을 `admin`으로 부여한다.
[x] 가입/로그인/초기 유저 생성 흐름을 정리한다: `blueprints/auth/forms.py`, `blueprints/auth/routes/register.py`, `blueprints/auth/routes/login.py`, `blueprints/xero/routes/routes.py`에서 legacy role 입력과 분기를 제거하고 신규 사용자는 기본 `system_role=normal`로 생성한다.
[x] 엔티티 역할 관리에서 shadow copy를 제거한다: `blueprints/user_management/routes/create_user.py`와 `blueprints/user_management/routes/roles.py`에서 `User.role` 동기화를 없애고 `UserEntity.role`만 authoritative 하게 유지한다.
[x] admin/system 전용 화면을 전환한다: `blueprints/user_management/routes/admin_list.py`, `blueprints/user_management/routes/admin_dashboard.py`, `blueprints/user_management/routes/approve_reject_access.py`와 관련 템플릿을 `system_role == "superuser"` 기준으로 바꾸고, normal 사용자는 admin 시스템에 들어가지 못하게 유지한다.
[x] API 응답과 UI 표시를 정리한다: `/minty/api/users/me` 응답, `templates/admin*.html`, `templates/report_detail.html`, `templates/report_list-copy.html`에서 legacy `role` 의존을 제거하고 `system_role` 또는 membership 정보만 노출한다.
[x] 테스트를 갱신한다: `tests/test_permission_policy.py`, `tests/test_user_permission_matrix_coverage.py`, `tests/test_authz_decorators.py`, `tests/test_invitation.py`를 새 모델에 맞게 수정하고, normal 사용자의 Entity 생성, creator의 admin bootstrap, `superuser` override를 검증한다.
[x] 문서와 운영 절차를 마무리한다: `remove_user_role.md`, 권한 문서, 배포 순서, 데이터 검증 쿼리, rollback 포인트를 정리하고 one-shot migration 기준의 수동 시나리오와 `pytest` 실행 계획을 기록한다.

## Open questions
- 없음. 핵심 정책 결정은 위 `Fixed decisions`로 확정한다.
