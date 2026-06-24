# S3 upload/download/delete helpers for report files (expenses). Use lazy
# app import for s3_client/S3_BUCKET.
import io
import os
import time
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import (ClientError, NoCredentialsError,
                                 PartialCredentialsError)
from dateutil import parser
from flask import current_app as app
from flask import g
from loguru import logger
from werkzeug.utils import secure_filename

from blueprints.report.services.file_downsize import downsize_bytes


def get_s3_bucket():
    return app.config.get("S3_BUCKET") or os.environ.get(
        "S3_BUCKET") or "pettycash"


def get_s3_client():
    if not hasattr(g, "_report_s3_client"):
        region = app.config.get("S3_REGION")
        if region:
            client = boto3.client(
                "s3",
                aws_access_key_id=app.config.get("S3_KEY"),
                aws_secret_access_key=app.config.get("S3_SECRET"),
                region_name=region,
                endpoint_url=f"https://s3.{region}.backblazeb2.com",
                config=Config(signature_version="s3v4"),
            )
        else:
            client = boto3.client(
                "s3",
                aws_access_key_id=app.config.get("S3_KEY"),
                aws_secret_access_key=app.config.get("S3_SECRET"),
            )
        g._report_s3_client = client
    return g._report_s3_client


def upload_file_to_s3(
    file,
    report_id,
    transaction_date=None,
    description=None,
    amount=None,
    file_index=None,
    max_retries=2,
):
    original_filename = secure_filename(file.filename)
    _, ext = os.path.splitext(original_filename)
    if not ext:
        ext = ".jpg"

    if transaction_date and description and amount is not None:
        if isinstance(transaction_date, str):
            transaction_date = parser.parse(transaction_date).date()
        date_str = transaction_date.strftime(
            "%d %b %Y").upper().replace(" ", "_")
        clean_description = description.upper().strip()
        clean_description = (
            clean_description.replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
            .replace("?", "")
            .replace("*", "")
            .replace('"', "")
            .replace("<", "")
            .replace(">", "")
            .replace("|", "")
        )
        clean_description = clean_description.replace(" ", "_")
        clean_description = "_".join(
            filter(None, clean_description.split("_")))
        amount_str = str(int(round(amount)))
        base_filename = f"{date_str}_{clean_description}_{amount_str}"
        if file_index is not None and file_index > 0:
            base_filename = f"{base_filename}_{file_index + 1}"
        filename = f"{base_filename}{ext}"
    else:
        name, _ = os.path.splitext(original_filename)
        filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"

    s3_key = f"expenses/{report_id}/{filename}"

    file.seek(0)
    raw = file.read()
    downsized, out_mime = downsize_bytes(raw, file.mimetype or "")
    # A PNG re-encoded to JPEG must land under a .jpg key so the stored bytes
    # match the extension that download/preview relies on.
    if out_mime == "image/jpeg" and not s3_key.lower().endswith((".jpg", ".jpeg")):
        s3_key = os.path.splitext(s3_key)[0] + ".jpg"
    if len(downsized) < len(raw):
        logger.info(
            f"Downsized {file.filename}: {len(raw)} -> {len(downsized)} bytes"
        )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            get_s3_client().upload_fileobj(
                io.BytesIO(downsized), get_s3_bucket(), s3_key
            )

            return s3_key
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait_time = 2**attempt
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} for file {file.filename} after {wait_time}s: {str(e)}"
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    f"Failed to upload file {file.filename} after {max_retries + 1} attempts: {str(e)}"
                )

    if last_error is None:
        raise RuntimeError(
            "Failed to upload file to S3 due to an unknown error.")
    raise last_error


def download_file_from_s3(s3_key):
    try:
        response = get_s3_client().get_object(Bucket=get_s3_bucket(), Key=s3_key)
        file_data = response["Body"].read()
        return file_data
    except NoCredentialsError:
        print("S3 credentials not found.")
    except PartialCredentialsError:
        print("Incomplete S3 credentials configuration.")
    except Exception as e:
        print(f"Error fetching file from S3: {e}")
    return None


def delete_files_from_s3(file_paths):
    if not file_paths:
        return

    objects_to_delete = [{"Key": path} for path in file_paths]
    try:
        get_s3_client().delete_objects(
            Bucket=get_s3_bucket(), Delete={
                "Objects": objects_to_delete, "Quiet": True})
    except ClientError as e:
        logger.warning(f"Failed to delete some files from S3: {e}")
