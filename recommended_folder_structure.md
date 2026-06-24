# 권장 폴더 구조 (현재 프로젝트 기준)

## 목표
- `app.py`는 애플리케이션 진입점(조립기)으로 유지하고, 비즈니스 로직과 라우트 본문은 분리
- 블루프린트는 라우트 바인딩 전용으로 유지
- 서비스/유틸/리포지토리 계층으로 책임 분리
- `blueprints`는 얇은 어댑터, 실제 로직은 `services`에서 수행

## 권장 구조

```text
.
├─ main.py
├─ app.py   # thin entrypoint / 호환 레이어 (권장: 최대 수십 라인)
├─ recommended_folder_structure.md
├─ refactoring_plan.md
├─ pettycash/
│  ├─ __init__.py
│  ├─ core/
│  │  ├─ bootstrap.py        # 앱 팩토리(create_app) + 기본 초기화 조립
│  │  ├─ blueprint_loader.py  # 블루프린트 등록
│  │  └─ hooks.py            # 공통 훅, 에러 핸들러, 세션 정리
│  └─ app_runtime/          # 기존 app.py의 핵심 실행 컨텍스트 분리
│     ├─ __init__.py
│     └─ legacy_bootstrap.py  # 현재 잔여 레거시(유지보수 단계) 모듈
│
├─ blueprints/
│  ├─ auth/
│  ├─ entity/
│  ├─ report/
│  ├─ xero/
│  ├─ admin/
│  ├─ user_management/
│  ├─ api/
│  └─ file/
│
├─ services/
│  ├─ entity/
│  ├─ report/
│  ├─ xero/
│  ├─ helpers/
│  └─ legacy/               # app.py에서 옮길 임시 보관 구역(단계적 분해용)
│      └─ handlers.py
│
├─ utils/
│  ├─ __init__.py
│  ├─ entity.py
│  ├─ report.py
│  └─ ...
│
├─ models/
├─ templates/
├─ static/
└─ tests/
```

## 1차 분리 우선순위 (app.py 경량화)
1. `app.py`를 thin shim으로 축소
2. 앱 생성/초기화 책임을 `pettycash/core/bootstrap.py`로 이동
3. 기존 `app.py`의 레거시 실행 로직/헬퍼를 `services/legacy/*`로 옮겨 임시 격리
4. 블루프린트/서비스 import에서 `from app import ...` 의존을 점진적으로 제거
5. 레거시에서 사용 빈도가 낮은 함수부터 서비스로 전환

## 운영 기준
- `app.py`에 라우트/비즈니스 로직/도메인 유틸이 직접 노출되지 않음
- 실행 가능한 경로는 `main.py`만 `create_app()` 호출
- 모듈 단위로 임포트 비용/책임 경계가 보이도록 유지