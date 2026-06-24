# refactoring_output.md

## Refactor Summary
- 목표: `blueprints/` 하위 기능 단위를 `routes`, `models`, `schemas`, `services`, `forms` 모듈로 분리해 유지보수성과 테스트 단위 분리를 강화.
- 적용 범위: `auth`, `entity`, `report`, `user_management`, `xero`.

## 변경 내용

### 1) Blueprint 라우팅 모듈 정리
- 각 blueprint의 라우팅 파일을 `blueprints/<blueprint>/routes/`로 이동.
- `blueprints/<blueprint>/__init__.py`에서 `blueprints.<blueprint>.routes`를 import 하여 기존 블루프린트 등록 방식 유지.

이동 파일
- `blueprints/auth/routes/*.py`
- `blueprints/entity/routes/*.py`
- `blueprints/report/routes/*.py`
- `blueprints/user_management/routes/*.py`
- `blueprints/xero/routes/*.py`

### 2) Blueprint 서비스 모듈 정리
- 각 blueprint의 비즈니스 로직 파일을 `blueprints/<blueprint>/services/`으로 이동.
- 라우트 모듈에서 service import 경로를 `blueprints.<blueprint>.services` 기준으로 변경.

이동 파일
- `blueprints/auth/services/*.py`
- `blueprints/entity/services/*.py`
- `blueprints/report/services/*.py`
- `blueprints/user_management/services/*.py`
- `blueprints/xero/services/*.py`

### 3) 스키마/모델/폼 계층 정비
- 각 blueprint에 공통 도메인 모델/스키마/폼 진입점을 추가.
- 신규/재배치 파일:
  - `blueprints/auth/models.py`, `blueprints/auth/schemas.py`, `blueprints/auth/forms.py`
  - `blueprints/entity/models.py`, `blueprints/entity/schemas.py`, `blueprints/entity/forms.py`
  - `blueprints/report/models.py`, `blueprints/report/schemas.py`
  - `blueprints/user_management/models.py`, `blueprints/user_management/schemas.py`, `blueprints/user_management/forms.py`
  - `blueprints/xero/models.py`, `blueprints/xero/schemas.py`

### 4) 기존 import 호환성 레이어
- 기존 코드(legacy)와의 호환을 위해 `services/<blueprint>/` 경로는 프록시 형태로 유지.
- 해당 파일들은 내부적으로 `blueprints/<blueprint>/...` 모듈을 재-export.
- `models/user_management.py` 또한 `blueprints.user_management.models`를 재-export하는 shim으로 전환.

## 체크 포인트
- 블루프린트별 라우트 등록( `blueprints/*/routes/__init__.py` ) 추가 및 초기화.
- 서비스 import를 신규 경로로 변경했으나, blueprint 내부 service 간에 기존 `services.*` 경로를 참조하는 내부 import 일부가 남아 있어, 현재는 위 호환 shim으로 동작 보장.
- 큰 기능 변경(동작 로직 수정) 없이 리팩터링(이동/분리)만 수행.

## 추가 정리 결과 (요청 반영)
- `blueprints/` 하위 서비스 파일들 내부의 `from services.<기능>...` 임포트를 전량 `blueprints.<기능>.services...` 계열로 치환.
- 대상 범위: `blueprints/auth/services`, `blueprints/entity/services`, `blueprints/report/services`, `blueprints/user_management/services`, `blueprints/xero/services`.
- 남은 `services.<...>` 의존성은 `services/*` 레거시 shim 경유로만 필요할 경우 유지되므로, 블루프린트 내부(동일/타 blueprint) 의존성은 `blueprints` 기준으로 통일됨.

## 모델 분해 추가 작업
- `models/db.py`의 ORM 클래스 정의를 blueprint별 `blueprints/<기능>/models/<모델명>.py`로 이동.
- 각 `models` 파일은 package로 전환(`blueprints/<기능>/models/` 디렉터리)하고, 클래스 단위를 파일 단위로 분리.
  - `blueprints/auth/models/user.py`
  - `blueprints/entity/models/{entity.py,user_entity.py,country_info.py,currency_info.py,cash_info.py,entity_cash_detail_v2.py,sale_info.py}`
  - `blueprints/report/models/{report.py,report_draft.py,shop_expense.py,shop_expense_draft.py,report_history.py,report_history_draft.py,report_cash_count_draft.py,report_v2.py,report_detail.py,report_history_v2.py,report_expense_detail.py,report_sale_detail.py,share_link.py,report_cash_detail.py}`
  - `blueprints/user_management/models/{roles.py,permissions.py,role_permissions.py}`
  - `blueprints/xero/models/{account_info.py,entity_account_xero.py,xero_contact_sync.py,xero_report_sync.py,xero_bank_transfer.py,xero_bank_transaction.py}`
- `models/db.py`는 각 blueprint 패키지의 모델을 임포트해 기존 `from models.db import ...` 호환을 유지.
