"""Automatic refresh of the public site data. Rebuilds the aggregates from the listings in the state folder (the same build as `make site-data`),
checks that they are still aggregates and not worse than what is live (`site_checks.py`), publishes the site to Netlify through its file-digest
API, checks the live site, and restores the previous deploy if that check fails. Runs at the end of the monthly job; `python -m src.pipeline site
--dry-run` builds and judges without publishing, and `site-rollback` restores the previous deploy by hand.
Needs SITE_URL, NETLIFY_SITE_ID and NETLIFY_AUTH_TOKEN (a secret) in the environment; without SITE_URL it does nothing, so local runs are safe."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from src.config import ROOT, STATE
from src.pipeline.site_checks import data_problems, guard_problems

API = "https://api.netlify.com/api/v1"
WEB = ROOT / "web"
STATIC = ["index.html", "style.css", "app.js", "config.js", "format.mjs", "share.mjs", "search.mjs", "_headers"]  # the site's own files; the data comes from the build
MARKER = "SITE REFRESHED"  # the log line the "site refreshed" alert policy matches (scripts/pipeline_alert.py)
LAST = STATE / "site" / "last.json"
READY_WAIT_S, LIVE_WAIT_S = 600, 90


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def build_data(out: Path) -> None:
    """The site data into `out`: the same script as `make site-data`, run as a subprocess so its output folder is a scratch one."""
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "scripts.build_site_data"], env={**os.environ, "SITE_OUT": str(out)}, cwd=ROOT, check=True)


def assemble(data: Path, dist: Path) -> None:
    """The folder that gets published: the static site files and the freshly built data."""
    dist.mkdir(parents=True, exist_ok=True)
    for name in STATIC:
        if not (WEB / name).exists():
            raise RuntimeError(f"web/{name} is missing from the image: rebuild it with the site files")
        shutil.copy2(WEB / name, dist / name)
    shutil.copytree(data, dist / "data", dirs_exist_ok=True)


def digests(dist: Path) -> dict[str, str]:
    """{"/index.html": sha1, ...} for every file in the folder, the body of a Netlify file-digest deploy."""
    return {"/" + path.relative_to(dist).as_posix(): sha1(path) for path in sorted(dist.rglob("*")) if path.is_file()}


def client(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}", "User-Agent": "site-refresh"}, timeout=120, transport=transport)


def upload(api: httpx.Client, site_id: str, dist: Path) -> str:
    """Publish the folder: send the digests, upload what Netlify does not have, wait until the deploy is ready. Returns the deploy id."""
    files = digests(dist)
    created = api.post(f"/sites/{site_id}/deploys", json={"files": files}).raise_for_status().json()
    needed, deploy_id = set(created.get("required", [])), created["id"]
    for path, digest in files.items():
        if digest in needed:
            needed.discard(digest)  # files with the same content only need to go once
            api.put(f"/deploys/{deploy_id}/files/{quote(path.lstrip('/'), safe='/')}", content=(dist / path.lstrip("/")).read_bytes(),
                    headers={"Content-Type": "application/octet-stream"}).raise_for_status()
    deadline = time.monotonic() + READY_WAIT_S
    while (state := api.get(f"/deploys/{deploy_id}").raise_for_status().json()["state"]) != "ready":
        if state == "error" or time.monotonic() > deadline:
            raise RuntimeError(f"Netlify deploy {deploy_id} ended in state {state}")
        time.sleep(5)
    return deploy_id


def live_problems(url: str, expected_listings: int) -> list[str]:
    """The live site must serve the new data and its security headers (the CDN can lag a few seconds, so the data is polled)."""
    deadline, served = time.monotonic() + LIVE_WAIT_S, None
    while time.monotonic() < deadline:
        served = httpx.get(f"{url}/data/meta.json", timeout=30).json().get("listings_total")
        if served == expected_listings:
            break
        time.sleep(5)
    problems = [] if served == expected_listings else [f"the live site serves {served} listings, expected {expected_listings}"]
    page = httpx.get(f"{url}/", timeout=30)
    if page.status_code != 200 or "content-security-policy" not in page.headers:
        problems.append(f"the live page answers {page.status_code} and {'has' if 'content-security-policy' in page.headers else 'lacks'} its security headers")
    return problems


def publish(dist: Path, url: str, site_id: str, token: str, expected_listings: int, transport: httpx.BaseTransport | None = None) -> str:
    """Deploy, check the live site, and put the previous deploy back if the check fails. Returns the new deploy id."""
    with client(token, transport) as api:
        previous = api.get(f"/sites/{site_id}").raise_for_status().json()["published_deploy"]["id"]
        deploy_id = upload(api, site_id, dist)
        if problems := live_problems(url, expected_listings):
            api.post(f"/sites/{site_id}/deploys/{previous}/restore").raise_for_status()
            raise RuntimeError(f"live check failed, the previous deploy {previous} is restored: {'; '.join(problems)}")
        LAST.parent.mkdir(parents=True, exist_ok=True)
        LAST.write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "deploy": deploy_id, "previous": previous, "listings": expected_listings}), encoding="utf-8")
        return deploy_id


def refresh(deploy: bool = True) -> str:
    """Build, judge and (unless `deploy` is False) publish. Returns "skipped", "current", "dry-run" or "published"; raises when the data is not fit to publish."""
    url, site_id, token = os.environ.get("SITE_URL"), os.environ.get("NETLIFY_SITE_ID"), os.environ.get("NETLIFY_AUTH_TOKEN")
    if not url:
        print("site: SITE_URL is not set, refresh skipped")
        return "skipped"
    work = Path(tempfile.mkdtemp(prefix="site-"))
    try:
        build_data(work / "data")
        new, live = json.loads((work / "data" / "meta.json").read_text(encoding="utf-8")), httpx.get(f"{url}/data/meta.json", timeout=30).json()
        if problems := data_problems(work / "data") + guard_problems(new, live):
            raise RuntimeError("site refresh not published: " + "; ".join(problems))
        if new["listings_total"] == live["listings_total"]:
            print(f"site: already current ({live['listings_total']} listings)")
            return "current"
        summary = (f"{new['listings_total']} listings (live {live['listings_total']}), {new['kecamatan_shown']} priced kecamatan (live {live['kecamatan_shown']}), "
                   f"{new['h3_cells']} H3 cells (live {live['h3_cells']}), overall median {new['overall']['median']} (live {live['overall']['median']})")
        if not deploy:
            print(f"site: would publish {summary} [dry run]")
            return "dry-run"
        if not (site_id and token):
            raise RuntimeError("NETLIFY_SITE_ID and NETLIFY_AUTH_TOKEN are needed to publish")
        assemble(work / "data", work / "dist")
        deploy_id = publish(work / "dist", url, site_id, token, new["listings_total"])
        print(f"{MARKER} {summary}; deploy {deploy_id}")
        return "published"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def rollback() -> str:
    """Put the previous ready deploy back (by hand: python -m src.pipeline site-rollback, with the token and site id in the environment)."""
    site_id, token = os.environ["NETLIFY_SITE_ID"], os.environ["NETLIFY_AUTH_TOKEN"]
    with client(token) as api:
        current = api.get(f"/sites/{site_id}").raise_for_status().json()["published_deploy"]["id"]
        older = [d for d in api.get(f"/sites/{site_id}/deploys", params={"per_page": 20}).raise_for_status().json() if d["id"] != current and d.get("state") == "ready"]
        if not older:
            raise RuntimeError("no earlier ready deploy to go back to")
        api.post(f"/sites/{site_id}/deploys/{older[0]['id']}/restore").raise_for_status()
    print(f"site: restored deploy {older[0]['id']} (was {current})")
    return older[0]["id"]
