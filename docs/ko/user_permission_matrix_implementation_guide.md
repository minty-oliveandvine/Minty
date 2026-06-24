# 사용자 권한 매트릭스 구현 가이드

문서 기준일: 2026-03-10  
대상 코드베이스: `minty-ref` (Flask monolith)

## 1) 목적

- `docs/ko/user_permission_matrix_explain.md`의 권한 요구사항을 실제 코드에 일관되게 반영한다.
- 현재 분산된 권한 체크(`current_user.role`, 부분적인 `UserEntity` 조회)를 정책 계층으로 통합한다.
- 권한 판단을 반드시 `entity_id` 컨텍스트 기준으로 수행하도록 강제한다.

## 1.1) 상태 업데이트 (2026-03-16)

- 중앙 권한 계층 `services/authz.py` + `services/permission_policy.py`가 이미 적용되어 있다.
- 전역 시스템 권한은 `User.system_role`(`normal` / `superuser`)로 정리되었고 `User.role`은 제거 대상이 아니라 이미 전환 범위에 들어갔다.
- `ENTITY_CREATE`는 인증된 `normal`/`superuser` 사용자에게 허용된다.
- 새 Entity를 만든 사용자는 해당 Entity의 `admin` membership을 즉시 부여받는다.
- admin 시스템 접근은 `system_role == "superuser"` 기준으로만 판정한다.
- 아래 문서의 "현재 상태" 섹션 중 일부는 리팩터링 이전 배경 설명이며, 현재 계약은 이 섹션을 우선 기준으로 본다.

## 2) 현재 상태 요약 (핵심 갭)

### 2.1 권한 로직 분산
- 권한 체크가 라우트별 문자열 비교와 서비스 내부 조건문에 흩어져 있다.
- 중앙 `require_permission`/`permission_policy`가 없다.

관련 코드:
- `docs/ko/01_architecture_overview.md`
- `blueprints/user_management/routes/admin_list.py`
- `blueprints/report/routes/report_detail.py`

### 2.2 Entity 컨텍스트 검증 불완전
- 다수 라우트가 `check_user_has_entities(user_id)`로 "엔티티 1개 이상 존재"만 확인한다.
- 대상 `entity_id`에 실제 멤버인지, 해당 역할이 맞는지 체크하지 않는 경로가 많다.

관련 코드:
- `blueprints/entity/services/shared.py`
- `blueprints/report/routes/history.py`
- `blueprints/report/routes/opening.py`
- `blueprints/report/routes/sales.py`
- `blueprints/report/routes/expense.py`
- `blueprints/report/routes/deposit.py`
- `blueprints/report/routes/cash_count.py`

### 2.3 고위험 엔드포인트 보호 부족
- `/minty/api/users/create`에 인증 데코레이터가 없다.
- 일부 Xero 관련 엔드포인트가 사실상 public/manual 상태다.

관련 코드:
- `blueprints/user_management/routes/create_user.py`
- `blueprints/xero/routes/routes.py`

### 2.4 요구사항과 구현 정렬 상태
- 엔티티 생성은 system-level action으로 정리되었고, 생성자는 `UserEntity.role = admin`으로 bootstrap 된다.
- 가입/로그인/Xero OAuth 초기 생성 흐름은 `User.system_role = normal`로 통일되었다.

관련 코드:
- `blueprints/entity/routes/create.py`
- `blueprints/auth/forms.py`
- `blueprints/auth/routes/register.py`
- `blueprints/xero/routes/routes.py`

### 2.5 역할/권한 테이블 미활용
- `roles`, `permissions`, `role_permissions` 스키마는 있으나 권한 엔진으로 실사용되지 않는다.

관련 코드:
- `blueprints/user_management/models/roles.py`
- `blueprints/user_management/models/permissions.py`
- `blueprints/user_management/models/role_permissions.py`

## 3) 구현 원칙

1. 권한 판단은 항상 `entity_id` 기준으로 수행한다.
2. 엔티티 권한은 `UserEntity.role`을 source of truth로 사용하고, 전역 시스템 권한은 `User.system_role`(`normal`/`superuser`)로만 분리한다.
3. View는 정책 판단을 직접 하지 않고 `데코레이터 + 정책 서비스`만 호출한다.
4. "본인 데이터"와 "엔티티 전체 데이터" 권한을 분리해서 모델링한다.
5. 사용자 비활성/삭제 시 과거 리포트/이력 데이터는 보존한다(soft delete 우선).

## 4) 목표 아키텍처

### 4.1 신규 모듈
- `services/permission_policy.py`
  - `Role` enum
  - `Permission` enum
  - `ROLE_HIERARCHY`
  - `PERMISSION_MATRIX`
  - `resolve_role(user_id, entity_id)`
  - `has_permission(user, permission, entity_id, resource=None)`

- `services/authz.py` (또는 `utils/authz.py`)
  - `require_permission(permission, entity_arg="entity_id")`
  - `require_entity_access(entity_arg="entity_id")`
  - 공통 403 응답/리다이렉트 처리

### 4.2 정책 모델
- Role 후보: `cashier`, `shop_manager`, `accountant`, `admin`, `super_admin`, `entity_base`
- Permission 예시:
  - User: `USER_INVITE`, `USER_VIEW_ALL`, `USER_ROLE_ASSIGN`, `USER_ROLE_DELETE`
  - Entity: `ENTITY_CREATE`, `ENTITY_VIEW`, `ENTITY_UPDATE`, `ENTITY_DELETE`
  - Sales Method: `SALES_METHOD_CREATE`, `SALES_METHOD_UPDATE`, `SALES_METHOD_DELETE`
  - CoA: `COA_CREATE`, `COA_UPDATE`, `COA_DELETE`
  - Report: `REPORT_CREATE`, `REPORT_VIEW_OWN`, `REPORT_VIEW_ENTITY`, `REPORT_EDIT`, `REPORT_DELETE_OWN`, `REPORT_DELETE_ENTITY`
  - Xero: `XERO_CONNECT`, `XERO_UPDATE`, `XERO_DISCONNECT`, `XERO_PUBLISH`, `XERO_REPUBLISH`, `XERO_VIEW_PUBLISH`

## 5) 코드 반영 우선순위

## Phase 1: 보안 핫픽스 (즉시)

1. `blueprints/user_management/routes/create_user.py`
- `@login_required` 추가
- `USER_INVITE` 권한 체크 추가
- 요청 본문의 `company_uuid`를 기준으로 `entity_id` 권한 검증

2. `blueprints/xero/routes/routes.py`
- 다음 엔드포인트에 인증/권한 체크 추가:
  - `/entity/settings/xero/disconnect`
  - `/api/entity/<entity_id>/xero-data`
  - `/api/xero/bank-transactions/latest/<entity_id>`
  - `/api/xero/bank-transactions/update/<entity_id>`

3. `blueprints/report/routes/report_detail.py`
- `/report/delete/<id>`에 최소 소유권 또는 엔티티 권한 체크 추가

## Phase 2: 매트릭스 기반 치환

1. `blueprints/entity/routes/settings.py`
- `entity_settings`, `entity_settings_entity`, `entity_contact_create`에 역할 권한 부여
- `entity_settings_users`에 사용자 전체 조회 권한 적용

2. `blueprints/entity/routes/payment.py` + `blueprints/entity/services/payment_methods.py`
- 현재의 단순 멤버십 체크를 Permission 체크로 교체
- `Cashier`는 조회만 가능하도록 제한

3. `blueprints/report/routes/*`
- `check_user_has_entities` 중심 조건을 `require_entity_access + require_permission`으로 교체
- "내 작성 리포트"와 "엔티티 전체 리포트" 권한을 분리 반영

4. `blueprints/report/routes/submitted.py`
- 게시/재게시 권한을 `Accountant+`로 제한
- `Shop Manager`는 게시 조회만 허용

## Phase 3: 데이터 정규화 및 호환

1. system role 계약 고정 + 마이그레이션
- `User.system_role` 허용값은 `normal`, `superuser`만 유지
- 기본값은 `normal`
- legacy 전역 role은 `admin`/`super_admin`만 `superuser`로 승격하고 나머지는 `normal`로 수렴

2. 엔티티 생성 role 정책 반영
- `ENTITY_CREATE`는 인증된 `normal`/`superuser` 사용자에게 허용
- 엔티티 생성 시 생성자 `UserEntity.role = admin` 강제
- `User.role` fallback은 제거하고, system-level override는 `User.system_role == "superuser"`로만 처리

3. 가입 정책 통일
- 일반 가입/Xero OAuth 가입의 초기 role 정책 일치화

## Phase 4: 테스트 체계

1. 정책 단위 테스트
- 역할 x 권한 x 리소스 소유권 조합 테스트
- 최소 매트릭스 테이블 테스트 추가

2. 라우트 통합 테스트
- 핵심 엔드포인트 403/200/302 케이스
- 엔티티 멤버십 없는 경우 차단
- role 변경 시 접근 결과 변동 검증

3. 회귀 방지
- `scripts/generate_permission_matrix.py` 결과를 CI 아티팩트로 비교
- 고위험 엔드포인트 인증 데코레이터 누락 감지 룰 추가

## 6) 사용자 삭제/비활성 정책

요구사항: "사용자 삭제/역할 변경 후에도 과거 생성 데이터는 보존"

권장:
- 물리 삭제 대신 soft delete (`is_active`, `deleted_at`) 도입
- `report.uploaded_by`/`report_draft.uploaded_by`는 문자열 보존
- `report_history.user_id`는 이미 `ondelete='SET NULL'`이므로 이력은 유지됨

주의:
- `user_entity`는 `ondelete='CASCADE'`이므로 물리 삭제 시 멤버십은 사라진다.
- 운영 정책상 "사용자 비활성화"를 기본 경로로 사용해야 데이터 추적 안정성이 높다.

## 7) 문서/운영 동기화

1. 권한 정책 소스 오브 트루스는 코드(`Permission enum + matrix`)로 둔다.
2. `docs/permissions_route_matrix_all_current.md` 생성 스크립트를 배포 파이프라인 또는 CI에서 주기 실행한다.
3. 정책 변경 시 다음 3종을 동시 갱신한다.
- 코드 매트릭스
- 테스트 케이스
- `docs/ko/user_permission_matrix_explain.md` (및 구현 가이드 문서)

## 8) 즉시 실행 체크리스트

- [ ] `services/permission_policy.py` 생성
- [ ] `require_permission` 데코레이터 생성
- [ ] `create_user` 인증/권한 보호
- [ ] Xero 고위험 API 인증/권한 보호
- [ ] `entity payment methods` 역할 제한 적용
- [ ] `report delete/edit/publish` 권한 명시화
- [ ] role 정규화 마이그레이션 초안 작성
- [ ] 권한 테스트 파일 추가

## 9) 확인 필요 사항

1. `docs/ko/user_permission_matrix_explain.md`에서 참조하는
   `docs/ko/user_permission_matrix_new_required.md` 파일이 현재 저장소에 없음.
2. 해당 원문 요구사항이 확인되면 `TBD` 항목을 Permission enum에 최종 반영해야 함.

