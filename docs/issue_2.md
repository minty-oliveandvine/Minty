# Issue 2

## 주제

Xero 설정 화면에서 특정 동작 후 `/index`로 이동하는 현상과,  
`xero_user_credential` 브랜치에서 이 문제가 해결되었는지에 대한 확인 기록.

## 1. 현재 이슈 해석

### 사용자가 체감한 증상

- 사용자가 Xero 설정 화면에 진입함
  - 예: `/entity/{entity_id}/settings/xero`
- 이후 `Disconnect` 또는 `Reconnect`와 관련된 동작을 시도함
- 기대한 화면으로 돌아가지 않고 `302` 후 `/index`로 이동함

### 로그 기준으로 본 흐름

1. Xero 관련 데이터 조회 요청 발생
   - `GET /api/entity/{entity_id}/xero-data`
2. 이어서 disconnect 요청 발생
   - `GET /entity/settings/xero/disconnect?entity_id=...`
3. 이 요청이 `302`
4. 직후 `GET /index`

즉, 실제 사용자 관점의 이슈는 아래와 같이 정리할 수 있음.

> "Xero 설정 화면에서 특정 버튼을 누르면 `/index`로 이동한다."

### 1차 판단

이 현상은 callback URL 자체가 잘못되었다기보다,  
권한 체크에서 막힌 뒤 fallback으로 `/index`로 이동하는 흐름일 가능성이 높음.

근거는 다음과 같음.

- Xero settings 화면은 조회 권한으로 접근 가능함
- 그러나 `Disconnect` / `Reconnect`는 수정 권한이 필요함
- 권한 데코레이터에서 접근이 막히면 `auth.index`로 redirect 하도록 되어 있음

즉,

- 화면은 볼 수 있음
- 버튼도 보임
- 하지만 실제 실행 권한은 없음
- 버튼 클릭 시 서버에서 막고 `/index`로 보냄

이 구조로 보임.

### 추가로 보인 문제

#### 1. 토큰 refresh 반복

로그상 refresh 성공 후에도 계속 만료로 판단되어 refresh가 반복되는 흔적이 있음.

원인 후보:

- refresh 후 `token_created_at`이 갱신되지 않음
- 그 결과 다음 요청에서도 즉시 만료로 판정됨

#### 2. Xero contacts 조회 `403`

로그에 아래와 같은 흐름이 있었음.

- `get_contacts_from_xero`
- `Request URL: https://api.xero.com/api.xro/2.0/Contacts?order=Name ASC`
- `Fetched contacts from Xero: <Response [403]>`

이 부분은 권한 문제, tenant 문제, stale token 문제 중 하나일 수 있음.
단, 로그만으로는 정확한 단정은 어려움.

#### 3. 비정상 referrer

로그에 아래와 같은 referrer가 보임.

- `.../entity/{id}/settings/xero%22`

즉, URL 끝에 `%22`가 포함되어 있어 `"` 문자가 붙은 상태로 보임.

이건 잘못된 링크 생성 또는 브라우저에서 잘못 조합된 URL 가능성을 시사함.
다만 코드 검색만으로는 직접적인 원인을 바로 특정하지 못했음.

## 2. 현재 기준 결론

현재 이슈의 핵심은 callback URL 오타보다는 아래 두 가지에 더 가까움.

### 핵심 원인 후보

1. 권한 정책과 UI 노출이 일치하지 않음
2. 토큰 refresh 처리도 비정상적임

### 가장 가능성이 높은 설명

이번 `/index` 이동 현상 자체는 아래 설명이 가장 자연스러움.

> "사용자는 Xero 설정 화면을 볼 권한은 있지만, Disconnect/Reconnect를 실행할 권한은 없어서, 버튼 클릭 후 권한 fallback으로 `/index`에 도달했다."

## 3. 어떻게 고치는 것이 맞는가

### 권장 수정 방향

#### 1. Xero settings UI와 권한 정책을 맞춘다

- 수정 권한이 없는 사용자는 `Disconnect` / `Reconnect` 버튼을 보지 못하게 하거나 비활성화
- 최소한, 화면에서 가능한 것처럼 보이는데 서버에서 `/index`로 튕기는 구조는 없애야 함

#### 2. 권한 실패 시 `/index` fallback을 재검토한다

- 현재처럼 무조건 `/index`로 보내면 사용자는 원인을 이해하기 어려움
- 가능하면 현재 entity settings 화면으로 돌려보내고 안내 메시지를 보여주는 편이 맞음

#### 3. refresh 성공 시 `token_created_at`을 갱신한다

- 그래야 refresh 직후 다시 만료 판정이 나지 않음

### 수정 후 기대 동작

- 조회만 가능한 사용자는 Xero settings 화면은 볼 수 있음
- 하지만 수정 권한이 없는 경우 Disconnect/Reconnect 버튼은 보이지 않거나 누를 수 없음
- 수정 권한이 있는 사용자가 버튼을 누르면 Xero settings 화면으로 정상 복귀
- 토큰은 필요 시 한 번만 refresh되고, 이후 요청마다 반복 refresh되지 않음

## 4. `xero_user_credential` 브랜치 확인 결과

## 결론

`xero_user_credential` 브랜치는 이 이슈를 완전히 해결한 상태는 아님.

정확히는 아래처럼 나눠서 보는 것이 맞음.

### 해결되지 않은 부분

#### `/index`로 튀는 현상

이 증상은 여전히 남아 있을 가능성이 높음.

확인 결과, 해당 브랜치에는 아래 파일 변경이 없음.

- `services/authz.py`
- `services/permission_policy.py`
- `templates/entity/settings.html`
- `pettycash/core/hooks.py`

즉, 아래 항목들은 그대로일 가능성이 큼.

- 권한 실패 시 `/index`로 보내는 fallback
- Xero settings 화면에서 버튼이 계속 노출되는 문제
- 현재 사용자 기준 반복 refresh 흐름

따라서 아래 질문에 대한 답은 `아니오`에 가까움.

> "`xero_user_credential` 브랜치에서 사용자가 버튼을 눌렀을 때 `/index`로 이동하는 문제까지 해결되었는가?"

정답:

> 아직 해결된 것으로 보기 어려움

### 개선된 부분

#### entity-scoped Xero credential 처리

이 브랜치에서는 Xero 인증 정보를 `current_user` 중심에서 `entity` 중심으로 옮기는 작업이 크게 들어가 있음.

변경된 주요 파일:

- `services/auth/token_service.py`
- `blueprints/xero/routes/routes.py`
- `blueprints/entity/routes/settings.py`
- `blueprints/xero/services/integration.py`
- `services/helpers/xero_bridge.py`

이 변경으로 개선된 점:

- entity 기준 credential 조회
- entity 기준 tenant 조회
- Xero settings 데이터 조회 시 user token 의존도 감소
- disconnect 흐름도 entity-scoped connection 쪽으로 이동

즉, 아래 문제는 이 브랜치에서 상당 부분 개선되었을 가능성이 있음.

> "잘못된 user token 또는 stale user token 때문에 Xero API 호출이 실패하는 문제"

### 여전히 애매하거나 남아 있는 부분

#### 반복 refresh 문제

`xero_user_credential` 브랜치에서는 entity connection refresh 시 `token_created_at`이 갱신되도록 바뀜.

하지만 `current_user`를 대상으로 하는 `auto_refresh_token(current_user)`는 여전히 `token_created_at`을 갱신하지 않음.

즉,

- entity credential 쪽 refresh는 개선됨
- user token refresh 루프는 여전히 남아 있을 수 있음

따라서 아래 질문에 대한 답은 `부분 해결`이 맞음.

> "반복 token refresh 로그 문제도 이 브랜치에서 완전히 해결되었는가?"

정답:

> 완전 해결로 보기 어려움

## 5. 최종 정리

### 현재 운영 로그 기준 이슈 해석

- `/index` 이동의 1차 원인은 callback URL 오타보다 권한 fallback일 가능성이 높음
- 토큰 refresh 반복 문제도 별도로 존재함
- `settings/xero%22` 같은 비정상 URL 흔적도 있어 링크 생성 문제 가능성은 추가 확인 필요

### `xero_user_credential` 브랜치 평가

- `/index` 이동 문제: 해결 안 된 것으로 보임
- entity-scoped credential 처리: 상당 부분 개선됨
- 반복 refresh 문제: 일부만 개선됨

## 6. 실무적으로 전달할 수 있는 한 줄 요약

`xero_user_credential` 브랜치는 Xero 인증 구조는 많이 정리했지만,  
이번 이슈의 핵심인 "Xero 설정 화면에서 버튼 클릭 후 `/index`로 이동하는 현상" 자체는 아직 남아 있을 가능성이 높다.
