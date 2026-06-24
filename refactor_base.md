# Task 1 Baseline Snapshot (2026-03-04)

- 기준 커밋: `d49f18d`
- 현재 커밋: `d49f18d`
- 기준 파일: `app.py`

## 1) app.py 기준점
- 총 라인 수: `8572`
- 라우트 데코레이터 수: `28`
- `@app.route` 목록 (line, endpoint):
  - 488: `/health`
  - 809: `/xero_auth`
  - 818: `/xero_connect`
  - 830: `/xero_reconnect`
  - 866: `/callback`
  - 1393: `/api/refresh_xero_token`
  - 1398: `/api/generate_share_link`
  - 1895: `/Minty_Report/<path:entity_and_date>/`
  - 1963: `/Minty_Report_<path:entity_and_date>/ending`
  - 2560: `/api/xero/bank-transactions/latest/<entity_id>`
  - 2604: `/api/xero/bank-transactions/update/<entity_id>`
  - 3176: `/entity/<string:entity_id>/reports`
  - 3480: `/entity/<string:entity_id>/settings/xero`
  - 5257: `/remove/connections/all`
  - 5291: `/api/entity/<string:entity_id>/xero-sync-status`
  - 5299: `/entity/settings/xero/disconnect`
  - 5425: `/debug/xero-settings/<string:entity_id>`
  - 5473: `/entity/settings/users/<string:org_id>`
  - 5504: `/entity/settings/entity/<string:org_id>`
  - 5699: `/entity/contact/create`
  - 5895: `/api/entities/<string:entity_id>/payment-methods`
  - 5936: `/api/entities/<string:entity_id>/payment-methods`
  - 6046: `/api/entities/<string:entity_id>/payment-methods/reorder`
  - 6152: `/api/entities/<string:entity_id>/payment-methods/reorder`
  - 6234: `/api/entity/<string:entity_id>/xero-data`
  - 6359: `/api/check-dept-bank-yest/<string:entity_id>`
  - 8510: `/insert_xero_transaction`

## 2) 핵심 설정/상수 요약
- 환경 관련 키: `SECRET_KEY`, `WTF_CSRF_SECRET_KEY`, `LOCAL_DATABASE_URI`, `RDS_DATABASE_URI`, `S3_BUCKET`, `S3_KEY`, `S3_SECRET`, `S3_REGION`
- Xero/통신 키: `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI`, `XERO_API_BASE_URL`, `SPIRE_KEY`
- 앱 설정:
  - `SQLALCHEMY_DATABASE_URI`
  - `SQLALCHEMY_ENGINE_OPTIONS` (`pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`, `pool_pre_ping`)
  - `SESSION_TYPE`, `SESSION_SQLALCHEMY`, `SESSION_SQLALCHEMY_TABLE`, `PERMANENT_SESSION_LIFETIME`, `SESSION_COOKIE_*`, `WTF_CSRF_ENABLED`, `WTF_CSRF_SSL_STRICT`, `WTF_CSRF_TIME_LIMIT`
  - `MAX_CONTENT_LENGTH`, Mail 관련 설정(`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`)
- 앱 초기화 객체: `app`, `db`, `login_manager`, `csrf`, `mail`, `migrate`

## 3) 체크리스트 정합
- 이동 대상 후보 라우트 중 report 관련: 4개
- 이동 대상 후보 라우트 중 xero/entity/user-auth 관련: 23개
- 훅/라이프사이클: `before_request`, `after_request`, `teardown_request`, `errorhandler(500)`, `errorhandler(CSRFError)`, `health`
