# Working Report

- 작성일: 2026-03-10
- 브랜치: `permission`
- 기준 범위: `origin/main` 병합 기준점부터 현재 HEAD(`4c7dd29`)까지
- 시작 커밋: `4a47ea6b83d5d28a3c8576efab36ed3665df2485` (2025-10-20)

## 요약
본 범위는 총 811개 커밋(merge 제외 비-merge 589개)로, 기능 변경이 매우 광범위합니다. 핵심 변화는 권한 정책 중앙화 및 적용, 리포트/엔티티/Xero 경로의 권한 정합성 강화, 테스트 추가 및 인프라/타입 정합성 보완입니다.

## 범위 집계
- 총 커밋 수: 811
- 총 변경 파일 수: 266
- 전체 라인 변경: `+72,127 / -15,980`
- merge 커밋 수: 222

## 핵심 산출물
- [services/permission_policy.py](/C:/Users/david/workspace/minty-ref/services/permission_policy.py)
  - Permission enum과 역할 기반 규칙(
- [services/authz.py](/C:/Users/david/workspace/minty-ref/services/authz.py)
  - `require_permission`, `require_entity_access` 기반의 공통 가드 도입
- [blueprints/user_management/routes/create_user.py](/C:/Users/david/workspace/minty-ref/blueprints/user_management/routes/create_user.py)
  - 초대 API(`POST /minty/api/users/create`)에 `USER_INVITE` 권한 + 엔티티 컨텍스트 검증 적용
- [blueprints/user_management/routes/roles.py](/C:/Users/david/workspace/minty-ref/blueprints/user_management/routes/roles.py)
  - 역할 부여/삭제 API 권한화(`USER_ROLE_ASSIGN`, `USER_ROLE_DELETE`)
- [templates/entity/settings_users.html](/C:/Users/david/workspace/minty-ref/templates/entity/settings_users.html)
  - Add User UI에서 초대 API를 호출하는 인터페이스 존재(프론트-백 연동 경로 동작)
- [templates/register.html](/C:/Users/david/workspace/minty-ref/templates/register.html)
  - 회원가입 화면 템플릿
- [blueprints/auth/routes/register.py](/C:/Users/david/workspace/minty-ref/blueprints/auth/routes/register.py)
  - 회원가입 라우트 유지
- [plan.md](/C:/Users/david/workspace/minty-ref/plan.md)
  - 권한 매트릭스 체크리스트/결과 정리

## 핵심 변경(요약)
1. 권한 정책 정합성 정비
- 엔티티 문맥 기반(`entity_id`)으로 판단하는 정책을 도입하고, 권한별 최소 역할 기준을 중앙에서 관리
- 보고서 조회/편집/삭제, 결제수단, 엔티티 생성/조회/수정/삭제, Xero 설정/게시, 유저 초대/역할 관리 경로에 권한 반영 확대

2. 라우트 레이어 가드 체계화
- 기능별 라우트에 `@login_required` + `@require_permission` / `@require_entity_access` 가드 적용
- 특히 리포트 관련(`report`), 엔티티 관련(`entity`), 사용자관리(`user_management`), Xero 설정/동작(`xero`) 라우트에서 일관성 개선

3. 버그 수정/안정성 강화
- report/sale/payment method 처리, Xero publish 상태 관리, 직렬화, 배경 작업 스레드 컨텍스트 등 관련 보정
- 타입/임포트 정리, lint 및 pyright 대응, Docker/uv 의존성 정합성 정비

4. 테스트 보강
- 권한 데코레이터 및 policy 단위 테스트, 리포트/결제수단/뷰 접근권한 테스트 추가
- 실행 결과: `18 passed` + `10 passed`

## 2026-03-10 기준 체크 결과(요청 항목)
- 이메일로 가입: 구현됨
  - UI: [templates/register.html](/C:/Users/david/workspace/minty-ref/templates/register.html)
  - 라우트: [blueprints/auth/routes/register.py](/C:/Users/david/workspace/minty-ref/blueprints/auth/routes/register.py)
- Invitation(사용자 초대): 구현됨
  - UI(템플릿): [templates/entity/settings_users.html](/C:/Users/david/workspace/minty-ref/templates/entity/settings_users.html)
  - API: [blueprints/user_management/routes/create_user.py](/C:/Users/david/workspace/minty-ref/blueprints/user_management/routes/create_user.py)
- 템플릿에서 초대 인터페이스 제공: 구현됨
  - Add New User 모달/폼/`fetch('/minty/api/users/create', ...)` 호출 확인

## 2026-03-04~2026-03-10 중심 커밋 타임라인(요약)
- 2026-03-04: 대규모 리팩터링, imports 정비, uv/도커 정합성, 타입 에러 정리
- 2026-03-05: Xero publish/리포트/배포/타입 안정성 다수 수정
- 2026-03-06~03-09: report/결제수단/재계산 보정류
- 2026-03-10: 권한 정책 및 갭 클로징 라운드 마감
  - `4272a75` : 권한 매트릭스 구현 가이드 추가
  - `a9298e5` : Permission policy + authz 가드 초안 구현
  - `404ee41` : entity create / xero publish 권한 정렬
  - `86f066f` : gap 라운드 2
  - `2a72067` : gap 라운드 3
  - `3b1bf2b` : 리포트 ID 접근 가드 강화
  - `f9e1a38` : gap 라운드 5
  - `4c7dd29` : signup/invite 체크리스트 마무리 반영

## 테스트 결과
- `uv run pytest -q tests/test_authz_decorators.py tests/test_permission_policy.py`
  - 결과: `18 passed`
- `uv run pytest -q tests/test_view_routes.py tests/test_payment_methods_permissions.py tests/test_report_export_permissions.py`
  - 결과: `10 passed`

## 비고 및 후속 권장사항
- 변경 범위가 매우 넓어 일부 이전 커밋(2025 하반기~2026-03 초반)은 구조/리팩토링/버그 수습 성격이 혼재됨
- 관리자 보고용으로는 2026-03-04~03-10 핵심 권한 마감 구간을 본문과 별도 부록으로 구분하면 의사결정이 용이
