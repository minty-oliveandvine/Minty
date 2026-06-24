# 사용자 권한 매트릭스 목표(목표 상태)

기준: `C:\Users\david\workspace\minty-ref\docs\ko\user_permission_matrix_explain.md`

## 전제
- 역할은 엔티티별(`UserEntity.role`) 기준으로 평가한다.
- 한 사용자는 엔티티마다 서로 다른 역할을 가질 수 있다.
- 사용자의 삭제/비활성화는 권한 판단에서 제외하고, 과거 데이터 보존은 유지한다.
- `Cashier`는 기존 `cashier/client` 문자열 계열의 하위 호환을 고려해 정규화 대상이다.
- 전역 시스템 권한은 `User.system_role`로 분리하고, 허용값은 `normal`과 `superuser`만 유지한다.

## 역할 정의
- `Cashier`
- `Shop Manager`
- `Accountant`
- `Admin`
- `Super Admin`

## 핵심 기능 매트릭스

### 사용자(User)

| 기능 | Cashier | Shop Manager | Accountant | Admin | Super Admin |
|---|---|---|---|---|---|
| 회원가입(본인 계정) | 허용 | 허용 | 허용 | 허용 | 허용 |
| 초대 | 불가 | 허용 | 허용 | 허용 | 허용 |
| 개인 조회 | 허용 | 허용 | 허용 | 허용 | 허용 |
| 전체 조회 | 불가 | 허용 | 허용 | 허용 | 허용 |
| 본인 수정 | 허용 | 허용 | 허용 | 허용 | 허용 |
| 역할 조회 | 불가 | 허용 | 허용 | 허용 | 허용 |
| 역할 설정/변경 | 불가 | 허용(자신 이하) | 허용(자신 이하) | 허용(자신 이하) | 허용 |
| 삭제(본인) | 허용 | 허용 | 허용 | 허용 | 허용 |
| 역할 삭제 | 불가 | 불가 | 허용 | 허용 | 허용 |

### 엔티티(Entity)

| 기능 | Cashier | Shop Manager | Accountant | Admin | Super Admin |
|---|---|---|---|---|---|
| 생성 | 허용* | 허용* | 허용* | 허용* | 허용* |
| 조회 | 허용 | 허용 | 허용 | 허용 | 허용 |
| 수정 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 삭제 | 불가 | 불가 | 불가 | 허용 | 허용 |

주석:

- `ENTITY_CREATE`는 기존 membership role로 판정하지 않는다.
- 인증된 `normal`/`superuser` 사용자는 기존 엔티티 소속이 없어도 새 Entity를 생성할 수 있다.
- Entity 생성 직후 생성자의 `UserEntity.role`은 `admin`으로 bootstrap 한다.

### Sales Method(결제 수단)

| 기능 | Cashier | Shop Manager | Accountant | Admin | Super Admin |
|---|---|---|---|---|---|
| 생성 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 조회 | 허용 | 허용 | 허용 | 허용 | 허용 |
| 수정 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 삭제 | 불가 | 불가 | 허용 | 허용 | 허용 |

### CoA 설정

| 기능 | Cashier | Shop Manager | Accountant | Admin | Super Admin |
|---|---|---|---|---|---|
| 생성 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 조회 | 허용 | 허용 | 허용 | 허용 | 허용 |
| 수정 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 삭제 | 불가 | 불가 | 허용 | 허용 | 허용 |

### Report(Daily)

| 기능 | Cashier | Shop Manager | Accountant | Admin | Super Admin |
|---|---|---|---|---|---|
| 생성 | 허용 | 허용 | 허용 | 허용 | 허용 |
| 조회(본인 작성) | 허용 | 허용 | 허용 | 허용 | 허용 |
| 조회(엔티티 기준) | 불가 | 허용 | 허용 | 허용 | 허용 |
| 수정 | 허용 | 허용 | 허용 | 허용 | 허용 |
| 삭제(본인 작성) | 허용 | 허용 | 허용 | 허용 | 허용 |
| 삭제(엔티티 기준) | 불가 | 허용 | 허용 | 허용 | 허용 |

### Report History

| 기능 | Cashier | Shop Manager | Accountant | Admin | Super Admin |
|---|---|---|---|---|---|
| 조회(본인 작성) | 허용 | 허용 | 허용 | 허용 | 허용 |
| 조회(엔티티 기준) | 불가 | 허용 | 허용 | 허용 | 허용 |

### Xero

| 기능 | Cashier | Shop Manager | Accountant | Admin | Super Admin |
|---|---|---|---|---|---|
| 연결 생성/수정/삭제 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 설정페이지 조회 | 허용 | 허용 | 허용 | 허용 | 허용 |
| 설정페이지 수정 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 설정페이지 삭제 | 불가 | 불가 | 불가 | 불가 | 불가 |
| 게시 생성 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 게시 조회 | 불가 | 허용 | 허용 | 허용 | 허용 |
| 재게시 | 불가 | 불가 | 허용 | 허용 | 허용 |
| 게시 삭제 | 불가 | 불가 | 불가 | 불가 | 불가 |

## 구현 시점의 강제 규칙(요약)
- 전역 시스템 권한은 `User.system_role`(`normal`/`superuser`)로만 관리한다.
- legacy `User.role`은 `admin`/`super_admin`만 `superuser`로 승격하고 나머지는 `normal`로 매핑한 뒤 제거한다.
- 엔티티 관련 모든 쓰기/조회는 반드시 `(사용자, 엔티티)` 맵핑(`UserEntity`)을 기반으로 확인한다.
- `ENTITY_CREATE`는 예외적으로 system-level action이며, 인증된 `normal`/`superuser` 사용자에게 허용한다.
- Entity 생성자는 생성 직후 해당 Entity의 `admin` membership을 받는다.
- `report/<id>` 조회/수정/삭제는 작성자/역할별 허용범위를 정책 함수로 계산한다.
- `Cashier/Shop Manager/Accountant/Admin/Super Admin` 외 상태는 정책 확정 후 즉시 반영한다.
