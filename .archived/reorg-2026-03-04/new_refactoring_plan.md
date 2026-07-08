# minty-ref ~ 현재 구간 재구성 실행 계획

## 기준점/범위
- 기준점: `minty-ref` HEAD = `d49f18d93e51aa872636ae10075e11c6d04f460e`
- 현재점: `f8f6e528d384abe73f35fec3143f4416741aed3d`
- 대상 구간: `d49f18d..f8f6e52`
- 총 커밋 수(병합/병합제외): **127개**

현재 구간은 크게 4단계로 나뉘어 있다.
- 1단계: report/route 서비스 분리 (대규모 리팩토링)
- 2단계: 권한/엔티티 스코프 재설계 (RBAC + 권한 매트릭스)
- 3단계: Xero 보안/토큰 경계 강화
- 4단계: 마지막 정합성 고정(계정턴트 조회 제한, 테스트/CI 강화)

## commit 기준 타임라인 (요약)
`d49f18d` → `329c641`(squash) → `0ef699a` → `...` → `f8f6e52`

주요 커밋 시퀀스:

1. `329c641` squash: consolidate refactor changes from be5f6f1..HEAD
2. `0ef699a`~`f27f70f`: report/service 분해 + routes 패키지 재편 + legacy routes.py 제거
3. `a095950`~`78345d7`: permission policy 첫 적용, 엔티티 스코프 role 권한 설계, active entity 정합
4. `7dd8438`~`c8a7e00`: signup/onboarding, xero token 보안, entity approval, sidepanel 및 인증 경로 정리
5. `b7e5ab9`~`63dcd5e`: xero_utils/로그/리커넥트/토큰 갱신 리팩토링
6. `9a3440d`~`524e2a6`: 라우트/URL 정합성 보정, entity settings 안정화
7. `96842f2`~`1c515fa`: RBAC todo 완료, permission UI 노출, 테스트 문서/매트릭스 동기화
8. `e9f7354`~`a45a93c`: entity user 삭제/초대 UX, admin auth 정합
9. `8cd44fa`~`f8f6e52`: role 기반 report 접근 제어 고정 + accountant 조회 전용 + 리포트 가시성 제한
10. `c017563`~`b6cc6a2`: 생성 실패/트랜잭션/세션 이슈, 테스트 리팩토링, DB 안정성 보강

## minty-ref에서 다시 작성할 때 필요한 작업(Task + Prompt)

1. 기준점 고정 작업
   - Prompt: `minty-ref` 기준 커밋(`d49f18d`)에서 새 브랜치를 생성하고, 현재 브랜치와 병합 없이 `d49f18d..f8f6e52`의 커밋 목록을 저장한다.

2. 도큐먼트/작업 기준 정리
   - Prompt: 기존 `working_report`와 permission matrix 문서를 기준 문서로 만들고, 작업 시작 전 완료/미완료 항목을 빈 상태(TODO로) 정리한다.

3. report 모듈 리팩토링(서비스 추출)
   - Prompt: `pettycash/blueprints/report`의 라우트에서 로직을 `pettycash/services/*`로 이동해 아래 순서로 서비스 분해한다: create/edit/delete/download/detail/list/resume/export/screenshot/sales/update/ending.
   - 포함 커밋: `3d96926`, `06cae1f`, `a12b61e`, `a42075a`, `6c6836e`, `dd49edf`, `e491b0a`, `a1dc158`, `937518e` 등

4. 라우트/패키지 구조 정리
   - Prompt: report/entity/auth/api 라우트에서 `routes.py` 의존을 폐기하고 패키지 구조(`routes/api`, `routes/views`, `routes/files`)로 이동해 앱 부팅 시 blueprint 등록점을 단일화한다.
   - 포함 커밋: `0e66068`, `f27f70f`, `cb303cb`, `04c526c`, `2e3a10d`, `2c11af4`, `3fc7aa2`, `06cae1f`, `4afc1b6`

5. 권한 정책 뼈대 수립
   - Prompt: `services/permission_policy` 또는 동등 구조를 만들고, report 삭제/공유/액션별 permission map을 역할 정책으로 정규화한다.
   - 포함 커밋: `a095950`, `22cf8be`, `73414b6`, `a4fcbb9`, `f6377d5`, `f210da5`, `f34b507`, `5cccd37`

6. 엔티티 기반 권한 해석으로 전환
   - Prompt: `role` 단일 판단에서 `active_entity` + `approved membership` 기준으로 치환한다. 로그인/로그아웃 시 active entity context를 정리하고, 엔티티 생성/이동/리포트 접근 플로우를 정합한다.
   - 포함 커밋: `bea76bb`, `e57b7e0`, `849a5d5`, `78345d7`, `c16e79f`, `c8a7e00`, `15afee9`, `c9a3afa`

7. 사용자 등록/초대/엔티티 관리 보강
   - Prompt: self-signup/approval 흐름을 entity base 기준으로 정리하고, user invite/create/delete/user settings/role revoke 시 권한 부작용이 생기지 않도록 테스트를 강화한다.
   - 포함 커밋: `e78fc89`, `c30549a`, `39ed500`, `e9f7354`, `b2e2344`, `f6377d5`, `a2e5796`

8. Xero 연동 토큰 경계 하드닝(필수)
   - Prompt: Xero 토큰 조회/저장/갱신/재연결 경로를 entity 스코프 기반으로 고립시켜 다른 엔티티 토큰 오염이 안 생기도록 하고, 실패 시 rollback/safety 경로를 명확히 둔다.
   - 포함 커밋: `cb10274`, `f6ab91f`, `a42c90a`, `8c76c0a`, `63dcd5e`, `a731c53`, `1e42685`, `6e283e2`

9. 라우팅/URL 안정성 정리
   - Prompt: `entity_id` 누락/route 인수 불일치/리포트 단계 네비게이션 이슈를 모두 보정하고, resume/opening/stepper/endpoints를 통일한다.
   - 포함 커밋: `9a3440d`, `9f44bed`, `43a7dad`, `a00b1fe`, `5a084a4`, `5ecbd9a`, `e9165f9`

10. 사이드바/권한 피드백 UX 반영
   - Prompt: 권한이 없을 때의 deny 메시지/플래시/숨김 동작을 일관화하고 `admin`, `entity`, `report` 화면별 가시성 로직을 권한 matrix 기준으로 동기화한다.
   - 포함 커밋: `3072eae`, `f4d0698`, `3087b1c`, `84b58f8`, `40355eb`

11. RBAC 자동 점검 루틴 + CI 연동
   - Prompt: 권한 매트릭스 자동 생성/검증 스크립트와 docs 업데이트를 CI 단계로 묶고, 매 실행마다 산출물이 커밋에 반영되도록 한다.
   - 포함 커밋: `b888f94`, `f34b507`, `f210da5`, `96842f2`, `e8a0c4c`, `7e8dac1`, `6a5d1f7`

12. DB/트랜잭션/세션 회귀 보강
   - Prompt: xero token 컬럼 확장, SQLAlchemy stale connection recovery, InFailedSqlTransaction 연쇄 실패 보호를 추가하고 entity 생성 중단/로그인 컨텍스트 깨짐 케이스를 방지한다.
   - 포함 커밋: `c017563`, `0ad0299`, `c55b2b1`, `0314cdf`, `a776a6f`, `8c76c0a`, `8cd44fa`

13. Accountant 권한 고정 마무리
   - Prompt: accountant는 엔티티/Xero 설정 화면은 READ-ONLY, report 목록은 자기 리포트만 보게 하고 entity report view를 재확인하는 회귀 테스트를 추가해 종료한다.
   - 포함 커밋: `e8b1201`, `a45a93c`, `b923be0`, `5afc2b5`, `093b714`, `f8f6e52`

14. 최종 테스트/문서 동기화
   - Prompt: 위 작업 완료 후 report permissions, RBAC matrix, admin/auth, reconnect/xero token edge, route navigation 네 가지 축으로 회귀를 묶어 문서와 함께 완료 기록을 남긴다.

## 유의점
- 커밋 `329c641`은 큰 squash이므로 실제로는 그 이전의 내부 커밋이 압축되어 있음.
- `minty-ref` 기준 경로는 detached head 상태였으므로 브랜치 이름은 별도 지정 필요.
- 이 구간의 핵심은 "report 리팩토링 + 권한 구조 전환 + xero 토큰 스코프 보안 + accountant 권한 고정"의 4개 축이 인과적으로 연결되어 있다.
