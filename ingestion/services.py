"""CSV import pipeline: validate, normalize, de-duplicate, store."""
import csv
import io
import logging

from django.db import transaction
from django.utils import timezone

from billing.models import BillingRecord

from .adapters import RowError, parse_row, resolve_columns
from .models import ImportJob

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000
MAX_LOGGED_ERRORS = 50


def run_import(job, fileobj):
    """Import a billing CSV for job.cloud_account. Never raises for bad data;
    the outcome is recorded on the job."""
    job.status = ImportJob.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])
    try:
        raw = fileobj.read()
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        with transaction.atomic():
            _process(job, text)
    except UnicodeDecodeError:
        _fail(job, "The file is not UTF-8 encoded text.")
    except csv.Error as exc:
        _fail(job, f"The file could not be read as CSV ({exc}).")
    job.completed_at = timezone.now()
    job.save()
    # Log counts only - never billing values or account identifiers.
    logger.info(
        "import job %s finished: status=%s imported=%s rejected=%s duplicate=%s",
        job.pk, job.status, job.records_imported, job.records_rejected, job.records_duplicate,
    )
    return job


def _fail(job, message):
    job.status = ImportJob.FAILED
    job.error_message = message
    job.records_imported = 0


def _process(job, text):
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = reader.fieldnames
    if not header or not any((h or "").strip() for h in header):
        _fail(job, "The file is empty.")
        return
    provider = job.cloud_account.provider
    mapping, missing = resolve_columns(provider, header)
    if missing:
        _fail(
            job,
            "Missing required column(s) for a %s export: %s."
            % (job.cloud_account.get_provider_display(), ", ".join(missing)),
        )
        return

    errors, seen = [], set()
    imported = rejected = duplicate = 0
    batch = []

    def flush():
        nonlocal imported, duplicate
        if not batch:
            return
        existing = set(
            BillingRecord.objects.filter(
                user=job.user, record_hash__in=[r["record_hash"] for r in batch]
            ).values_list("record_hash", flat=True)
        )
        fresh = [r for r in batch if r["record_hash"] not in existing]
        duplicate += len(batch) - len(fresh)
        BillingRecord.objects.bulk_create(
            [
                BillingRecord(user=job.user, cloud_account=job.cloud_account, import_job=job, **r)
                for r in fresh
            ]
        )
        imported += len(fresh)
        batch.clear()

    for row in reader:
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue
        try:
            record = parse_row(provider, mapping, row)
        except RowError as exc:
            rejected += 1
            if len(errors) < MAX_LOGGED_ERRORS:
                errors.append({"row": reader.line_num, "reason": str(exc)})
            continue
        if record["record_hash"] in seen:
            duplicate += 1
            continue
        seen.add(record["record_hash"])
        batch.append(record)
        if len(batch) >= BATCH_SIZE:
            flush()
    flush()

    job.records_imported = imported
    job.records_rejected = rejected
    job.records_duplicate = duplicate
    job.error_log = errors
    if rejected and not imported and not duplicate:
        job.status = ImportJob.FAILED
        job.error_message = "No valid rows were found in the file."
    elif rejected:
        job.status = ImportJob.COMPLETED_WITH_ERRORS
    else:
        job.status = ImportJob.COMPLETED
