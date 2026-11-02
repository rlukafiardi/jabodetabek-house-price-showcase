"""Weekly usage check of the Google Cloud side against the free tier: Cloud Run requests (and 429s), vCPU-seconds and GiB-seconds of the `api`
service from Cloud Monitoring, the last 7 days and month to date, a full-month projection at the 7-day pace (month to date is too short to
project from early in a month), the image registry and the data bucket. The cost table itself is only in the console (Billing, Reports).
Runs as a stage of the weekly job (token from the metadata server) and by hand (`make usage`, token from ./gcloud.sh).
`usage()` returns warnings when a projection passes WARN_SHARE of a free amount, so the job fails and the alert emails."""

import calendar
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import httpx

PROJECT, REGION, SERVICE = "jabodetabek-house-price", "asia-southeast2", "api"
FREE = {"requests": 2_000_000, "vcpu_s": 180_000, "gib_s": 360_000}  # Cloud Run request-based billing, per month (free-features page, read 2026-10-31)
FREE_REGISTRY_GB, FREE_BUCKET_GB = 0.5, 5.0
WARN_SHARE = 0.5
METRICS = {"vcpu_s": "container/cpu/allocation_time", "gib_s": "container/memory/allocation_time", "instance_s": "container/billable_instance_time"}
METADATA = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"


def access_token() -> str:
    try:
        return httpx.get(METADATA, headers={"Metadata-Flavor": "Google"}, timeout=2).json()["access_token"]
    except httpx.HTTPError:  # not on Google Cloud: the project-local login
        return subprocess.run(["./gcloud.sh", "auth", "print-access-token"], check=True, capture_output=True, text=True).stdout.strip()


def get(token: str, url: str, **params) -> dict:
    response = httpx.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    response.raise_for_status()
    return response.json()


def series(token: str, metric: str, start: datetime, end: datetime, group_by: str | None = None) -> dict[str, float]:
    """Sum of one Cloud Run metric over [start, end), per value of `group_by` (or one total under "")."""
    iso = lambda t: t.isoformat().replace("+00:00", "Z")
    params = {"filter": f'metric.type="run.googleapis.com/{metric}" AND resource.labels.service_name="{SERVICE}"', "interval.startTime": iso(start),
              "interval.endTime": iso(end), "aggregation.alignmentPeriod": f"{int((end - start).total_seconds())}s", "aggregation.perSeriesAligner": "ALIGN_SUM",
              "aggregation.crossSeriesReducer": "REDUCE_SUM"}
    if group_by:
        params["aggregation.groupByFields"] = group_by
    totals: dict[str, float] = {}
    for s in get(token, f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries", **params).get("timeSeries", []):
        key = s["metric"].get("labels", {}).get(group_by.split(".")[-1], "") if group_by else ""
        totals[key] = totals.get(key, 0.0) + sum(float(p["value"].get("int64Value") or p["value"].get("doubleValue") or 0) for p in s["points"])
    return totals


def period(token: str, start: datetime, end: datetime) -> dict[str, float]:
    codes = series(token, "request_count", start, end, "metric.labels.response_code")
    out = {"requests": sum(codes.values()), "429s": codes.get("429", 0.0), "5xx": sum(v for k, v in codes.items() if k.startswith("5"))}
    out.update({name: series(token, metric, start, end).get("", 0.0) for name, metric in METRICS.items()})
    return out


def registry_gb(token: str) -> tuple[int, float]:
    images = get(token, f"https://artifactregistry.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/repositories/{SERVICE}/dockerImages").get("dockerImages", [])
    return len(images), sum(int(i.get("imageSizeBytes", 0)) for i in images) / 1e9


def bucket_gb(token: str) -> tuple[int, float]:
    names = [os.environ["BUCKET"]] if os.environ.get("BUCKET") else [b["name"] for b in get(token, "https://storage.googleapis.com/storage/v1/b", project=PROJECT).get("items", [])]
    total, page = 0, None
    for name in names:
        while True:
            listing = get(token, f"https://storage.googleapis.com/storage/v1/b/{name}/o", fields="items(size),nextPageToken", maxResults=1000, **({"pageToken": page} if page else {}))
            total += sum(int(o["size"]) for o in listing.get("items", []))
            if not (page := listing.get("nextPageToken")):
                break
    return len(names), total / 1e9


def usage() -> list[str]:
    token = access_token()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month, week = period(token, month_start, now), period(token, now - timedelta(days=7), now)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    print(f"Cloud Run `{SERVICE}` ({REGION}), {now:%Y-%m-%d %H:%M} UTC; month to date starts {month_start:%Y-%m-%d}")
    print(f"{'':12}{'last 7 days':>14}{'month to date':>16}{'month at 7-day pace':>22}{'free a month':>14}{'share':>8}")
    warnings = []
    for name in ("requests", "vcpu_s", "gib_s", "instance_s", "429s", "5xx"):
        projected = max(week[name] / 7 * days_in_month, month[name])
        free = FREE.get(name)
        print(f"{name:12}{week[name]:>14,.0f}{month[name]:>16,.0f}{projected:>22,.0f}{(f'{free:,}' if free else ''):>14}{(f'{projected / free:.1%}' if free else ''):>8}")
        if free and projected > WARN_SHARE * free:
            warnings.append(f"{name} projected at {projected / free:.0%} of the free amount")
    if week["5xx"]:
        warnings.append(f"{week['5xx']:.0f} server errors in the last 7 days: read the Cloud Run logs")
    images, reg = registry_gb(token)
    buckets, bucket = bucket_gb(token)
    print(f"image registry `{SERVICE}`: {images} image(s), {reg:.2f} GB of {FREE_REGISTRY_GB} GB free; buckets ({buckets}): {bucket:.3f} GB of {FREE_BUCKET_GB} GB free")
    if reg > FREE_REGISTRY_GB:  # cents a month: shown, but not worth a failed job and an email
        print(f"NOTE image registry above the free {FREE_REGISTRY_GB} GB: delete old images, or deploy the API on the job's image so only one is kept")
    print("Costs: console, Billing, Reports (group by SKU): Cloud Run should show its usage cancelled by 'Other savings' (the free-tier credit).")
    for w in warnings:
        print("WARN", w)
    return warnings


if __name__ == "__main__":
    sys.exit(1 if usage() else 0)
