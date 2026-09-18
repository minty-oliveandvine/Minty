# Receipts and attachments

Every expense line carries at least one receipt. The bytes live in the Backblaze B2 bucket
(spoken to through the S3 API — `blueprints/report/services/s3_storage.py`, `S3_KEY` /
`S3_SECRET` / `S3_REGION` / `S3_BUCKET`, endpoint `https://s3.<region>.backblazeb2.com`);
the database holds one `attachment` row per file and a link row per expense line.

## The rows

```
report_expense ──< report_expense_attachment >── attachment
                    (attachment_role, sort_order,     (file_path = the bucket key,
                     xero_attachment_id)               original_name, stored_name,
                                                       mime_type, file_size, uploaded_by)
```

`ReportExpense.attachments`, `.receipt_keys`, `.receipt` and the old `.files` (a
comma-joined string) and `.s3_key` (the first key) all read through the link rows; setting
`.files` or calling `add_receipt(...)` / `set_receipt_keys(...)` writes them
(`blueprints/report/models/shop_expense.py`). Deleting a line or a report cascades to the
link rows and the attachment rows only they used, and `delete_expense_with_receipts` also
deletes the objects from the bucket (F2, fixed in C4).

## Keys and names

`upload_file_to_s3` names an object `expenses/<report_id>/<DD_MON_YYYY>_<STEM>_<amount>.<ext>`
where the stem is the expense item (the account name) normalised by
`blueprints/report/services/receipt_keys.safe_stem` to **letters, digits and underscores
only** (`safe_extension` allows jpg/jpeg/png/gif/webp/pdf). Before 2026-09-18 the stem was
the item verbatim, so a name such as *Light, Power, Heating* put commas into the key, and
**1,186 production receipts carry such keys** — `split_receipt_keys` therefore splits the
old comma-joined `files` value only where the next key starts (`expenses/`, `attachments/`,
`uploads/`, `http`), never on a bare comma. That parser is the only thing that may split
that string: the templates iterate `expense.receipt_keys`, the routes call
`split_receipt_keys`. Splitting on every comma produced two keys no object has and the
"Key not found" preview the deployed app showed that day.

Images are downsized before storage (`services/file_downsize.py`, Pillow; a PNG may come
back as a JPEG, and the stored `mime_type` reflects the bytes actually stored).

## Reading them back

- The expense page's *view* modal and the report detail page link `GET /download/<key>`,
  which redirects to a presigned URL (1 hour; `blueprints/report/routes/download.py`). The
  API paths that create a line return a 15-minute presigned `preview_url`.
- `POST /download_attachments` (`start_date`, `end_date`, `company`) zips every receipt of
  the period as `<date>/<filename>`.
- The Xero publish uploads each receipt to the **Files API** and associates it with the
  bank transaction it belongs to (`upload_each_file`; stateless — it asks Xero what is
  already attached rather than tracking ids, see `minty-xero-publish-overwrite`).

## Tests

`tests/test_receipt_keys.py` (the parser and the naming), `tests/test_char_expense_attachments.py`
(rows, cascade, the old `files` shape), `tests/test_char_report_lifecycle.py::test_every_receipt_the_detail_page_shows_is_an_object_the_bucket_holds`
(plants a legacy comma key and proves the page links it whole, the download redirects to
it and the zip contains it) and, in the browser,
`e2e/02_report_wizard.spec.ts` "the stored receipt renders when the line is reopened"
(`brokenImages()` in `e2e/helpers.ts` fails on any image with `naturalWidth 0`; the
account used is *Light, Power, Heating* on purpose).
