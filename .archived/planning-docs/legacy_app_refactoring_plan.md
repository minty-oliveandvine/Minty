# legacy_app.py 완전 분해 체크리스트

- 작성일: 2026-03-04
- 기준 라인 수: `services/app_runtime/legacy/legacy_app.py` = **109행** (최초 기준)
- 현재 라인 수: **31행**
- 현재 함수 수: `def` 0개
- 현재 라우트 수: `@app.route` 0개
- 현재 legacy 참조 잔여: 없음 (`services.app_runtime.legacy.legacy_app` 직접 import 미발생)

### 실무 점검 반영 (2026-03-04)
- [x] 추천 폴더 구조 정합성 점검: 런타임 구조는 `main.py`, `app.py`, `pettycash/`, `blueprints/`, `services/`, `models/`, `templates/`, `static/`, `utils/` 중심으로 정돈
- [x] 추천 구조와 맞지 않는 사용불가/의미없는 잔여 디렉터리·파일(캐시, 로그/DB 임시본, 임시 테스트 산출물)를 삭제하지 않고 `.archived/reorg-2026-03-04`로 격리
- [x] `__pycache__` 및 `.pytest_cache`를 `.archived/reorg-2026-03-04/pycache`, `generated-artifacts`로 이관
- [x] 빈 폴더(`config/`, `tests/` 및 하위 빈 폴더)를 `.archived/reorg-2026-03-04/empty-directories`로 이관

## 목표 기준
- `legacy_app.py`를 **300~700행** shim/호환 레이어로 축소
- 기존 엔드포인트 동작 동치 유지
- legacy 직접 import 소거 및 순환참조 정리
- 각 단계 완료 시 라인 수 재측정

## 체크리스트

### 0) 시작 상태 기록
- [x] `legacy_app.py` 라인 수를 재측정하여 기준값으로 저장
  - 확인 명령: `Get-Content services/app_runtime/legacy/legacy_app.py | Measure-Object -Line`
- [x] 함수 목록 캡처
  - 확인 명령: `rg -n '^def ' services/app_runtime/legacy/legacy_app.py`
- [x] 라우트 목록 캡처
  - 확인 명령: `rg -n '^@app\.route\(' services/app_runtime/legacy/legacy_app.py`
- [x] 템플릿/JS에서 사용하는 엔드포인트명 매핑 목록 정리
  - 확인 명령: `rg -n 'url_for\("[a-zA-Z0-9_]+"' templates blueprints services | Select-Object -First 500`

### 1) bootstrap + compat 구조 정리
- [x] `services/app_runtime/legacy/bootstrap.py` 생성
- [x] `services/app_runtime/legacy/compat.py` 생성 (legacy 호환 객체 재노출용)
- [x] `services/app_runtime/legacy/__init__.py`를 위 파일 위주로 재노출
- [x] `services/app_runtime/legacy/legacy_app.py`에서 애플리케이션 생성/초기화 블록 제거
- [x] `xero_sync_status` 상태 소유권을 xero 서비스 계층으로 이동(또는 명확히 shim 재노출로 전환)
- [x] 체크: bootstrap 분리 후 앱 기동 성공 (`SESSION_TYPE=filesystem`에서 `APP_OK` 검증 완료)
- [x] `app`, `db`, `login_manager`, `csrf`, `mail`, `migrate` 가 legacy 호환으로 노출되는지 확인

### 2) 공통 유틸/필터 정리
- [x] `comma_format`을 report helper 모듈로 이동 (`services/helpers/formatter.py` 또는 `services/report/shared.py`)
- [x] `convert_docx_to_pdf` 위치 정리
- [x] `get_xero_response_text` 위치 정리
- [x] `load_user`, `check_user_has_entities`, `get_account` 계열 임포트 의존을 도메인 모듈로 정리
- [x] `legacy_app.py`에 남는 helper 정의가 0개인지 점검

### 3) Report 도메인 라우트 이동
- [x] `/api/generate_share_link` 이동
  - 라우트: `blueprints/report/*`
  - 서비스: `services/report/share.py`
- [x] `/entity/<string:entity_id>/reports` 이동
  - 라우트: `blueprints/report/history.py`
  - 서비스: `services/report/report_list_service.py`
- [x] `/entity/settings/xero` 계열 라우트( `/entity/<string:entity_id>/settings/xero`, `/entity/settings/users/<string:org_id>`, `/entity/settings/entity/<string:org_id>` ) 이동
  - 라우트: `blueprints/entity`
  - 서비스: `services/entity/*`
- [x] `/entity/contact/create` 이동 -> `blueprints/entity`
- [x] 결제수단 API 라우트 3개 및 reorder 라우트 이동
  - `GET/POST /api/entities/<string:entity_id>/payment-methods`
  - `PUT/DELETE /api/entities/<string:entity_id>/payment-methods/<string:method_id>`
  - `PUT /api/entities/<string:entity_id>/payment-methods/reorder`
- [x] `/remove/connections/all`, `/debug/xero-settings/<string:entity_id>` 이동
  - 라우트: `blueprints/xero`
- [x] 각 라우트 이동 후 `register_compat_alias`로 기존 엔드포인트명 회귀 점검

### 4) Xero 도메인 로직 이동
- [x] `send_to_xero`, `process_xero_integration_background`, `xero_integrated_module`을 서비스로 이동
- [x] `bank_transaction_to_xero`, `bank_transfer_to_xero`, `create_bank_transaction`, `create_bank_transfer` 이동
- [x] `get_latest_xero_bank_transactions`, `update_bank_transaction` 이동 완료
- [x] `xero_token` 동기화/갱신 및 예외 처리 로직 정리
- [x] `create_xero_contact`, `ensure_contact_exists_in_xero`, `get_contact` 이동/정리
- [x] `check_entity_xero_settings_complete`, `get_missing_xero_settings_fields`, `get_entity_account_settings`, `get_entity_xero_data`, `sync_entity_xero_status`, `remove_connections*`, `debug_xero_settings` 이동
- [x] 체크: Xero 라우트 핸들러는 thin wrapper인지 검증(비즈니스 로직 없음)

### 5) report 계산/정합성 로직 분리
- [x] `recalculate_report`, `recalculate_report_version_2` 정렬
- [x] `update_after_deposit_change`, `update_xero_report_sync` 정렬
- [x] `entity_ending`, `entity_ending_with_report`, `convert_report_to_draft` 정리
- [x] `insert_xero_transaction`, `check_dept_bank_yest_module` 서비스 이동
- [ ] 점검: 동일 결과를 반환하는지 샘플 시나리오 2건 실행

### 6) legacy_app 내부 정리
- [x] 라우트 반환 후 도달 불가 코드(legacy 구현 주석 블록) 삭제
- [x] 사용되지 않는 import 정리
- [x] 중복 로직(임포트 중복/타입 중복/미사용 변수) 제거
- [x] 남은 `legacy_app.py` 라인 수가 줄어든 최종값 기록
- [x] `legacy_app.py` 내 함수 재래핑 제거 (직접 재노출 방식으로 축소)

### 7) 의존성 역전/순환참조 제거
- [x] `services/app_runtime/legacy`에 대한 직접 의존 import를 서비스 코드에서 제거
  - `rg "services\.app_runtime\.legacy\.legacy_app" services`
- [x] import order 점검: blueprint -> service -> model -> util 구조 확인
- [x] `app.route`/`template_filter` 등록은 bootstrap 또는 blueprint 등록 구간으로 이동

### 8) 호환성 검증
- [x] 공유 링크 경로 점검
  - `/Minty_Report/<path:entity_and_date>/`
  - `/Minty_Report_<path:entity_and_date>/ending`
  - `insert_xero_transaction`
- [x] 핵심 API 경로 점검
  - `/entity/<string:entity_id>/reports`
  - `/entity/<string:entity_id>/settings/xero`
  - `/entity/settings/users/<string:org_id>`
  - `/entity/settings/entity/<string:org_id>`
  - `/api/entity/<string:entity_id>/xero-sync-status`
  - `/api/entities/<string:entity_id>/payment-methods`
- [ ] Xero 상태 폴링, 결제수단 CRUD, report 제출/게시 플로우 수동 검증
- [x] `legacy_app.py` 최종 라인 수를 재기록 (**36행**)

### 9) 완료 판정
- [x] `git status`에서 `legacy_app.py`가 shim 파일 수준인지 확인
- [x] 기준 메트릭 재측정(라인/라우트/def 수)
  - 라인 수: `Measure-Object -Line`
  - 라우트 수: `rg -n '^@app\.route\('`
  - 함수 수: `rg -n '^def '
- [x] `services.app_runtime.legacy.legacy_app` 직접 참조 0건

## 위험/의사결정 항목
- [x] `xero_sync_status`는 단일 프로세스 기준 `defaultdict` 상태로 유지
- [x] legacy endpoint alias는 `url_for`에서 점이 없는 구식 호출(`approve_admins`, `delete_report`, `disconnect_from_xero`, `entity_report_history`, `entity_settings`, `entity_settings_entity`, `entity_settings_users`, `validate_register`, `xero_auth`, `xero_connect_entity`, `xero_reconnect`)을 `register_compat_alias`로 유지
- [x] `process_xero_integration_background`를 xero service 내부 백그라운드 유틸로 고정할지, route-local helper로 유지할지

## 단계별 커밋 제안
1. `refactor(legacy): move bootstrap initialization into legacy bootstrap layer`
2. `refactor(report): relocate remaining report routes from legacy_app`
3. `refactor(xero): move xero integration logic out of legacy_app`
4. `refactor(entity): move entity settings/payment methods to service layer`
5. `chore(legacy): remove unreachable legacy fallbacks and cleanup`
6. `chore(legacy): shrink legacy_app to compatibility shim`
7. `chore(legacy): add compat endpoint aliases and consolidate report history route logic`

