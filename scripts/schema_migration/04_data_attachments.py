#!/usr/bin/env python
"""지출 첨부 이관: shop_expense.files / .s3_key -> attachment + report_expense_attachment.

04_data_attachments.sql 과 같은 일을 하지만, 형식 파싱을 PL/pgSQL 로 이식하는
대신 앱의 ``normalize_expense_files`` 를 그대로 import 해서 쓴다. 파서가 한 벌만
존재하므로 앱과 이관 결과가 어긋날 수 없다 — 이 스크립트를 쓰는 유일한 이유다.

SQL 판과의 차이:
  * 파싱 로직 중복 없음 (services/shared.py 를 직접 호출)
  * ``--backfill-size`` 로 S3 head_object 를 호출해 file_size / checksum 을 채움
    (SQL 로는 불가능)
  * 진행 상황과 형식별 분포를 리포트

사용법:
    # 미리보기 — 아무것도 쓰지 않고 파싱 결과만 출력
    python scripts/schema_migration/04_data_attachments.py --dry-run

    # 실제 이관
    python scripts/schema_migration/04_data_attachments.py --commit

    # 이관 + S3 에서 크기/체크섬 백필 (느림: 파일당 API 1회)
    python scripts/schema_migration/04_data_attachments.py --commit --backfill-size

환경변수:
    RDS_DATABASE_URI (또는 LOCAL_DATABASE_URI)  대상 DB
    TARGET_SCHEMA    기본 pettycash_test
    SOURCE_SCHEMA    기본 pettycashv2
    --backfill-size 사용 시 추가로 S3_BUCKET / S3_KEY / S3_SECRET / S3_REGION

전제: 03_data_reports.sql 이 COMMIT 된 상태 (report_expense 행이 있어야 함).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections import Counter
from pathlib import Path

import psycopg2
import psycopg2.extras

# 앱 모듈을 import 하기 위해 리포지토리 루트를 경로에 추가.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ★ 이 스크립트의 핵심: 앱의 파서를 그대로 쓴다.
from blueprints.report.services.shared import normalize_expense_files  # noqa: E402

SOURCE_SCHEMA = os.environ.get("SOURCE_SCHEMA", "pettycashv2")
TARGET_SCHEMA = os.environ.get("TARGET_SCHEMA", "pettycash_test")


def _db_url() -> str:
    url = os.environ.get("RDS_DATABASE_URI") or os.environ.get("LOCAL_DATABASE_URI")
    if not url:
        sys.exit("RDS_DATABASE_URI (또는 LOCAL_DATABASE_URI) 가 설정되지 않았습니다.")
    return url


def _classify(files_value: str | None) -> str:
    """리포트용 형식 분류. 파싱에는 영향을 주지 않는다."""
    if not files_value or not files_value.strip():
        return "empty"
    t = files_value.strip()
    if t.startswith("{") and t.endswith("}"):
        return "B-object"
    if t.startswith("[") and t.endswith("]"):
        return "C-array"
    return "A-csv" if "," in t else "A-single"


def _extension(key: str) -> str:
    ext = os.path.splitext(key)[-1].lower().lstrip(".")
    return ext[:20]


def collect(cur) -> list[dict]:
    """원본 두 테이블을 읽어 (report_expense_id, s3_key, ...) 로 펼친다.

    report_expense.id 는 03 에서 원본 PK 를 승계했으므로 원본 PK 로 조인한다:
      shop_expense          -> report_expense.id = shop_expense.id
      report_expense_detail -> report_expense.id = report_expense_detail.expense_id

    ★ 두 원본 테이블은 사실상 같은 지출을 가리킨다. 겹치는 id 10156건 중
    10155건은 경로 문자열까지 동일하다. 그래서 (지출, s3_key) 쌍으로 중복을
    제거한다.

    제거하지 않아도 UNIQUE (report_expense_id, attachment_id) 덕분에 최종
    데이터는 같다. 하지만 (1) 리포트 숫자가 두 배로 부풀고 — 22917 vs 실제
    11691 — (2) sort_order 가 어느 쪽이 먼저 들어오느냐에 따라 달라진다.
    운영자는 --dry-run 숫자를 보고 진행 여부를 판단하므로 첫 번째가 더
    위험하다.

    s3_key 단독으로 묶지 않는 이유: 같은 파일이 서로 다른 지출 546건에 걸쳐
    쓰인다. 첨부는 지출과 M:N 이므로 쌍 자체가 곧 링크다.
    """
    rows: list[dict] = []
    stats: Counter[str] = Counter()
    seen: set[tuple] = set()
    order_of: Counter = Counter()
    orphans = 0
    dupes = 0

    def add(src_id, files_value, s3_key_col) -> None:
        """파싱 결과를 rows 에 추가. 이미 본 (지출, 키) 쌍은 건너뛴다."""
        nonlocal dupes
        for f in normalize_expense_files(files_value, s3_key_col):
            key = f.get("s3_key")
            if not key:
                continue
            if (src_id, key) in seen:
                dupes += 1
                continue
            seen.add((src_id, key))
            rows.append(
                {
                    "report_expense_id": src_id,
                    "s3_key": key,
                    "display_name": f["display_name"],
                    "mime_type": f["mime_type"],
                    # 지출별 일련번호. 한 필드 안의 순서를 그대로 이어받으면서,
                    # 두 원본이 서로 다른 파일을 줄 때 order 가 충돌하지 않는다.
                    "sort_order": order_of[src_id],
                }
            )
            order_of[src_id] += 1

    # --- shop_expense (files + s3_key) ---------------------------------------
    cur.execute(
        f"""
        SELECT se.id AS src_id, se.files, se.s3_key,
               (re.id IS NOT NULL) AS has_target
        FROM {SOURCE_SCHEMA}.shop_expense se
        LEFT JOIN {TARGET_SCHEMA}.report_expense re
               ON re.id = se.id::uuid
        WHERE COALESCE(btrim(se.files), '') <> ''
        """
    )
    for r in cur.fetchall():
        stats[_classify(r["files"])] += 1
        if not r["has_target"]:
            orphans += 1
            continue
        add(r["src_id"], r["files"], r["s3_key"])

    # --- report_expense_detail (info_filepath, s3_key 대응 컬럼 없음) ---------
    # At alembic head (r10a10) this table no longer exists: r5a05 folded its
    # rows into shop_expense, so the block above already saw every path. The
    # read is kept for a pre-consolidation source and skipped otherwise.
    cur.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = 'report_expense_detail'
        """,
        (SOURCE_SCHEMA,),
    )
    if cur.fetchone() is None:
        print("  report_expense_detail 없음 (alembic head) — shop_expense 만 읽음")
    else:
        cur.execute(
            f"""
            SELECT ed.expense_id AS src_id, ed.info_filepath AS files,
                   (re.id IS NOT NULL) AS has_target
            FROM {SOURCE_SCHEMA}.report_expense_detail ed
            LEFT JOIN {TARGET_SCHEMA}.report_expense re
                   ON re.id = ed.expense_id::uuid
            WHERE COALESCE(btrim(ed.info_filepath), '') <> ''
            """
        )
        for r in cur.fetchall():
            stats[_classify(r["files"])] += 1
            if not r["has_target"]:
                orphans += 1
                continue
            add(r["src_id"], r["files"], None)

    print("  원본 형식 분포:", dict(stats))
    if dupes:
        print(
            f"  두 원본에 걸쳐 중복된 첨부 {dupes}건 제거 "
            f"— shop_expense 와 report_expense_detail 은 같은 지출을 가리키며 "
            f"경로까지 거의 동일합니다."
        )
    if orphans:
        print(
            f"  ⚠ report_expense 가 없어 건너뛴 지출 {orphans}건 "
            f"— 03 단계에서 부모 리포트가 매칭되지 않은 경우입니다."
        )
    return rows


def _s3_metadata(keys: list[str]) -> dict[str, dict]:
    """S3 head_object 로 크기/체크섬을 조회. 실패한 키는 결과에서 빠진다."""
    import boto3
    from botocore.config import Config

    region = os.environ.get("S3_REGION")
    kwargs: dict = {
        "aws_access_key_id": os.environ.get("S3_KEY"),
        "aws_secret_access_key": os.environ.get("S3_SECRET"),
    }
    if region:
        kwargs.update(
            region_name=region,
            endpoint_url=f"https://s3.{region}.backblazeb2.com",
            config=Config(signature_version="s3v4"),
        )
    client = boto3.client("s3", **kwargs)
    bucket = os.environ.get("S3_BUCKET", "pettycash")

    out: dict[str, dict] = {}
    for i, key in enumerate(keys, 1):
        try:
            head = client.head_object(Bucket=bucket, Key=key)
            out[key] = {
                "file_size": head.get("ContentLength"),
                # ETag 는 멀티파트가 아니면 MD5. sha256 이 아니므로 저장하지
                # 않는다 — 잘못된 알고리즘의 값을 checksum_sha256 에 넣는 것은
                # NULL 보다 나쁘다.
                "checksum_sha256": None,
            }
        except Exception as exc:  # noqa: BLE001 — 개별 키 실패는 치명적이지 않다
            print(f"    [{i}/{len(keys)}] head_object 실패 {key}: {exc}")
        if i % 50 == 0:
            print(f"    [{i}/{len(keys)}] 조회 중…")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="쓰지 않고 파싱 결과만 출력")
    mode.add_argument("--commit", action="store_true", help="실제로 이관")
    ap.add_argument(
        "--backfill-size",
        action="store_true",
        help="S3 head_object 로 file_size 백필 (파일당 API 1회, 느림)",
    )
    args = ap.parse_args()

    conn = psycopg2.connect(_db_url())
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        print("1) 원본 읽기 + 파싱")
        rows = collect(cur)
        print(f"  파싱된 첨부 {len(rows)}건")

        by_key = {r["s3_key"]: r for r in rows}
        print(f"  고유 S3 키 {len(by_key)}건")

        multi = Counter(r["report_expense_id"] for r in rows)
        n_multi = sum(1 for c in multi.values() if c > 1)
        print(
            f"  첨부 2개 이상인 지출 {n_multi}건 "
            f"(단일 attachment_id 였다면 유실될 뻔한 건수, "
            f"최대 {max(multi.values()) if multi else 0}개)"
        )
        shared = Counter(r["s3_key"] for r in rows)
        n_shared = sum(1 for c in shared.values() if c > 1)
        print(
            f"  여러 지출이 공유하는 파일 {n_shared}건 "
            f"(attachment 은 한 번만 만들고 링크만 여러 개)"
        )

        if args.dry_run:
            print("\n  샘플 (최대 10건):")
            for r in rows[:10]:
                print(
                    f"    {r['s3_key']}  ->  {r['display_name']}  "
                    f"[{r['mime_type']}]  order={r['sort_order']}"
                )
            print("\n--dry-run 이므로 아무것도 쓰지 않고 종료합니다.")
            conn.rollback()
            return 0

        meta: dict[str, dict] = {}
        if args.backfill_size:
            print(f"\n2) S3 메타데이터 조회 ({len(by_key)}건)")
            meta = _s3_metadata(list(by_key))
            print(f"  조회 성공 {len(meta)}건 / 실패 {len(by_key) - len(meta)}건")

        print("\n3) attachment INSERT")
        # 이미 같은 file_path 로 들어온 행은 재사용한다 (재실행 안전).
        cur.execute(f"SELECT id, file_path FROM {TARGET_SCHEMA}.attachment")
        existing = {r["file_path"]: r["id"] for r in cur.fetchall()}

        att_rows = []
        key_to_id: dict[str, str] = {}
        for key, r in by_key.items():
            if key in existing:
                key_to_id[key] = existing[key]
                continue
            att_id = str(uuid.uuid4())
            key_to_id[key] = att_id
            m = meta.get(key, {})
            att_rows.append(
                (
                    att_id,
                    r["display_name"],
                    os.path.basename(key) or key,
                    key,
                    _extension(key),
                    r["mime_type"],
                    # attachment.file_size is NULLABLE for exactly this case:
                    # without --backfill-size nothing has asked S3 how big the
                    # object is, and NULL says that where 0 would lie.
                    m.get("file_size"),
                    "s3",
                    # checksum_sha256 is NOT NULL DEFAULT '' - _s3_metadata
                    # deliberately returns None rather than the ETag (see there),
                    # so coalesce to the empty string or every insert fails.
                    m.get("checksum_sha256") or "",
                    None,  # uploaded_by — 원본에 정보 없음
                )
            )

        if att_rows:
            psycopg2.extras.execute_values(
                cur,
                f"""
                INSERT INTO {TARGET_SCHEMA}.attachment
                  (id, original_name, stored_name, file_path, file_extension,
                   mime_type, file_size, storage_provider, checksum_sha256,
                   uploaded_by, created_at, updated_at)
                VALUES %s
                """,
                att_rows,
                template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now())",
            )
        print(f"  신규 {len(att_rows)}건 / 기존 재사용 {len(by_key) - len(att_rows)}건")

        print("\n4) report_expense_attachment INSERT")
        link_rows = [
            (
                str(uuid.uuid4()),
                r["report_expense_id"],
                key_to_id[r["s3_key"]],
                "receipt",
                r["sort_order"],
                "",
            )
            for r in rows
        ]
        # cur.rowcount 는 execute_values 의 마지막 페이지(기본 100행)만 세므로
        # 삽입 건수로 쓸 수 없다 — 11691건을 넣고 91을 보고한다. 전후 개수를
        # 직접 세어 차이를 보고한다.
        cur.execute(f"SELECT count(*) AS n FROM {TARGET_SCHEMA}.report_expense_attachment")
        before = cur.fetchone()["n"]
        if link_rows:
            psycopg2.extras.execute_values(
                cur,
                f"""
                INSERT INTO {TARGET_SCHEMA}.report_expense_attachment
                  (id, report_expense_id, attachment_id, attachment_role,
                   sort_order, xero_attachment_id, created_at)
                VALUES %s
                ON CONFLICT (report_expense_id, attachment_id) DO NOTHING
                """,
                link_rows,
                template="(%s,%s,%s,%s,%s,%s,now())",
            )
        cur.execute(f"SELECT count(*) AS n FROM {TARGET_SCHEMA}.report_expense_attachment")
        after = cur.fetchone()["n"]
        print(
            f"  연결 {after - before}건 삽입 / 이미 있어 건너뛴 건 "
            f"{len(link_rows) - (after - before)}건 (합계 {after}건)"
        )

        conn.commit()
        print("\n✅ COMMIT 완료")
        return 0

    except Exception:
        conn.rollback()
        print("\n❌ 실패 — 롤백했습니다.")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
