# User.role 전환 메모

작성일: 2026-03-16

## 현재 결론

- 전역 사용자 역할은 `User.role` 대신 `User.system_role`로 관리한다.
- `User.system_role` 허용값은 `normal`, `superuser` 두 개뿐이다.
- 엔티티 권한의 source of truth는 계속 `UserEntity.role`이다.
- `ENTITY_CREATE`는 기존 entity membership과 무관하게 인증된 사용자에게 허용한다.
- 새 Entity를 만든 사용자는 해당 Entity의 `admin` membership을 즉시 부여받는다.
- `superuser`는 membership 없이 모든 엔티티 접근이 가능한 system-level override를 유지한다.
- `User.role`은 dual-read / double-write 없이 one-shot으로 제거한다.

## 구현 상태

- `blueprints/auth/models/user.py`
  - `User.role`을 제거하고 `User.system_role`로 치환했다.
- `blueprints/auth/system_roles.py`
  - `normal` / `superuser` 정규화와 legacy 매핑 규칙을 고정했다.
- `services/permission_policy.py`
  - entity-scoped 권한의 global role fallback을 제거했다.
  - `superuser`만 system-level override로 유지한다.
  - `ENTITY_CREATE`는 인증된 사용자 기준으로 허용한다.
- `blueprints/entity/routes/create.py`
  - Entity 생성자를 `UserEntity.role = "admin"`으로 bootstrap 한다.
- `blueprints/auth/routes/register.py`
  - 가입 폼의 legacy role 입력을 제거하고 신규 사용자를 `system_role=normal`로 생성한다.
- `blueprints/xero/routes/routes.py`
  - Xero OAuth 신규 사용자도 `system_role=normal`로 생성한다.
- `blueprints/user_management/routes/create_user.py`
  - 초대/생성되는 사용자의 system role은 항상 `normal`이다.
- `blueprints/user_management/routes/roles.py`
  - membership role 변경/삭제 시 `User.system_role` shadow copy를 하지 않는다.
  - `/minty/api/users/me`는 `system_role`과 `memberships`를 함께 반환한다.
- `blueprints/user_management/routes/admin_list.py`
- `blueprints/user_management/routes/admin_dashboard.py`
- `blueprints/user_management/routes/approve_reject_access.py`
  - admin 시스템 접근은 `system_role == "superuser"` 기준으로만 판정한다.

## 현재 권한 모델

### 전역 시스템 권한

- `normal`
  - 기본값
  - 일반 로그인, Entity 생성, 일반 엔티티 접근 흐름 사용
- `superuser`
  - admin 시스템 접근 가능
  - 모든 엔티티에 membership 없이 접근 가능

### 엔티티 권한

- `cashier`
- `shop_manager`
- `accountant`
- `admin`

엔티티 권한은 모두 `UserEntity.role`로만 판단한다.

## 운영 배포 순서

1. DB 백업을 먼저 만든다.
2. `User.system_role` migration을 적용한다.
3. 애플리케이션 코드를 배포한다.
4. 배포 직후 검증 쿼리와 수동 시나리오를 수행한다.
5. 문제가 없으면 구버전 앱 인스턴스를 완전히 내린다.

중요:
- 이번 전환은 one-shot이다.
- DB에서 `user.role`이 제거된 뒤에는 구버전 애플리케이션을 그대로 재기동하면 안 된다.

## 데이터 검증 쿼리

### 1. `system_role` 분포 확인

```sql
SELECT system_role, COUNT(*)
FROM pettycashv2."user"
GROUP BY system_role
ORDER BY system_role;
```

### 2. `user.role` 컬럼 제거 여부 확인

PostgreSQL:

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'pettycashv2'
  AND table_name = 'user'
  AND column_name IN ('role', 'system_role');
```

기대 결과:

- `system_role`만 조회되고 `role`은 없어야 한다.

### 3. 엔티티 membership role 분포 확인

```sql
SELECT role, COUNT(*)
FROM pettycashv2.user_entity
GROUP BY role
ORDER BY role;
```

### 4. system role과 membership role 분리 상태 확인

```sql
SELECT u.id, u.email, u.system_role, ue.entity_id, ue.role
FROM pettycashv2."user" u
LEFT JOIN pettycashv2.user_entity ue
  ON ue.user_id = u.id
ORDER BY u.email, ue.entity_id;
```

확인 포인트:

- `system_role`은 `normal` 또는 `superuser`만 존재해야 한다.
- 엔티티 역할은 `UserEntity.role`에만 있어야 한다.

## 수동 검증 시나리오

1. 회원가입
   - 새 사용자를 가입시키고 DB에서 `system_role='normal'`인지 확인한다.
   - 로그인 후 `/index`로 이동하는지 확인한다.
2. 일반 사용자 Entity 생성
   - `normal` 사용자로 Entity를 생성한다.
   - 생성 성공 후 `user_entity`에 생성자 `role='admin'` row가 생기는지 확인한다.
3. admin 시스템 접근
   - `normal` 사용자는 `/admin`, `/admin_dashboard` 접근 시 차단되는지 확인한다.
   - `superuser`는 같은 경로에 접근 가능한지 확인한다.
4. 엔티티 역할 변경
   - 특정 엔티티에서 사용자의 membership role을 변경한다.
   - `User.system_role` 값은 그대로 유지되는지 확인한다.
5. 프로필 API
   - `/minty/api/users/me` 응답에 `system_role`과 `memberships`가 포함되는지 확인한다.

## 롤백 포인트

- 가장 안전한 롤백 포인트는 migration 적용 직전의 DB 백업이다.
- 앱 코드만 롤백하는 것은 안전하지 않다.
  - 이유: 구버전 코드는 `user.role` 컬럼을 기대할 수 있다.
- 장애 시 우선순위:
  1. 신규 배포 앱 중지
  2. DB를 migration 이전 백업으로 복원하거나 reverse migration 적용
  3. 그 다음에만 구버전 앱 재기동

## 테스트 실행 기준

아래 명령으로 주요 회귀 세트를 검증했다.

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_system_roles.py `
  tests/test_permission_policy.py `
  tests/test_user_permission_matrix_coverage.py `
  tests/test_authz_decorators.py `
  tests/test_invitation.py `
  tests/test_entity_create.py `
  tests/test_auth_register_login.py `
  tests/test_admin_system_role_routes.py `
  tests/test_user_management_membership_roles.py `
  tests/test_user_profile_contract.py `
  tests/test_view_routes.py
```

실행 결과:

- `112 passed`

## 남은 주의사항

- `blueprints/report/routes/download.py`의 `/admin/download_statements`는 이름상 admin 기능이지만 아직 `login_required`만 있다.
- 이번 `system_role` 전환과 별개로, 해당 라우트는 `superuser` 또는 별도 system permission으로 가드하는 후속 작업이 필요하다.
