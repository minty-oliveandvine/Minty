# Receipts and attachments

Every expense line carries at least one receipt. The bytes live in the Backblaze B2 bucket
(spoken to through the S3 API — `blueprints/report/services/s3_storage.py`, configured by one
`S3_URL` = `https://KEY:SECRET@s3.<region>.backblazeb2.com/<bucket>`, which gives the key,
secret, bucket, region and the endpoint `https://s3.<region>.backblazeb2.com`);
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
  which redirects to a presigned URL (1 hour; `blueprints/report/routes/download.py`) - only
  for a receipt of a report the person may see (`can_view_report`, via the attachment row or
  the `expenses/<report_id>/` key prefix). The
  API paths that create a line return a 15-minute presigned `preview_url`.
- **The preview (2026-10-05).** The Expenses step draws the receipt on the page, in the
  Payment Request app's look (`static/js/receipt_preview.js`): an image as itself, a PDF page by
  page with **pdf.js** (4.10.38, pinned, from jsDelivr on first use - Flask has no build step;
  an `<iframe>` shows nothing on Android and only page 1 on iOS). It shows in the Add Expense
  upload box (a PDF used to leave it empty), as page 1 on the Expense Details tile (a PDF was
  an icon), and larger in the receipt modal (the whole window, drawn at 2-3x for sharp print)
  from the upload box's eye, a tile or a click - never a new tab or a black overlay any more.
  A file that can't be drawn says why (damaged, locked, didn't come through).
- pdf.js fetches the file, so a saved receipt is read from this origin:
  `GET /preview/<key>` streams the bytes inline (same checks as `/download`: 404 / 403,
  logged; at most 10 MB, the upload limit, else 413). `/download` stays the redirect.
- `POST /download_attachments` (`start_date`, `end_date`, `company`) zips every receipt of
  the period as `<date>/<filename>`. Superuser only: a blank `company` means every company.
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
