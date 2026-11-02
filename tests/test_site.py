import json

import httpx
import pytest

from src.pipeline import site
from src.pipeline.site_checks import data_problems, guard_problems

REAL_CLIENT = httpx.Client  # tests replace httpx.Client, so keep the real one
LIVE = {"listings_total": 4000, "kecamatan_shown": 160, "h3_cells": 240, "overall": {"median": 14.0}}


def meta(**changes):
    return {**LIVE, "overall": dict(LIVE["overall"]), **changes}


def test_guards_pass_a_normal_refresh_and_stop_a_bad_one():
    assert guard_problems(meta(listings_total=4450, kecamatan_shown=165, h3_cells=260), LIVE) == []
    bad = guard_problems(meta(listings_total=3900, kecamatan_shown=120, h3_cells=200, overall={"median": 17.0}), LIVE)
    assert len(bad) == 4 and "fewer listings" in bad[0] and "priced kecamatan fell" in bad[1] and "H3 cells fell" in bad[2] and "median price" in bad[3]


def test_data_problems_flag_a_price_under_the_minimum_and_unknown_properties(tmp_path):
    feature = lambda **props: {"type": "Feature", "properties": props, "geometry": None}
    ok = {"type": "FeatureCollection", "features": [feature(code="1", name="A", city="B", n=9, median=10.0, p25=8.0, p75=12.0, cls=2, mixed=0)]}
    (tmp_path / "kecamatan.geojson").write_text(json.dumps(ok))
    (tmp_path / "h3.geojson").write_text(json.dumps(ok))
    assert data_problems(tmp_path) == []
    leaky = {"type": "FeatureCollection", "features": [feature(code="1", name="A", city="B", n=3, median=10.0, p25=8.0, p75=12.0, cls=2, mixed=0, phone="0812")]}
    (tmp_path / "kecamatan.geojson").write_text(json.dumps(leaky))
    problems = data_problems(tmp_path)
    assert any("unexpected properties" in p for p in problems) and any("3 listings carries a price" in p for p in problems)


def fake_netlify(requests, served=4450, csp=True, has_files=()):
    """A router for the Netlify API and the live site: records every call, answers the digest deploy flow."""
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET" and path == "/api/v1/sites/S":
            return httpx.Response(200, json={"published_deploy": {"id": "old-deploy"}})
        if request.method == "POST" and path == "/api/v1/sites/S/deploys":
            files = json.loads(request.content)["files"]
            return httpx.Response(200, json={"id": "new-deploy", "required": [d for p, d in files.items() if p not in has_files]})
        if request.method == "PUT":
            return httpx.Response(200, json={})
        if request.method == "GET" and path == "/api/v1/deploys/new-deploy":
            return httpx.Response(200, json={"state": "ready"})
        if request.method == "POST" and path.endswith("/restore"):
            return httpx.Response(200, json={"state": "current"})
        if path == "/data/meta.json":
            return httpx.Response(200, json={"listings_total": served})
        if path == "/":
            return httpx.Response(200, headers={"content-security-policy": "default-src 'none'"} if csp else {}, text="<html></html>")
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture
def dist(tmp_path, monkeypatch):
    folder = tmp_path / "dist"
    (folder / "data").mkdir(parents=True)
    (folder / "index.html").write_text("<html>page</html>")
    (folder / "_headers").write_text("/*\n  X-Frame-Options: DENY\n")
    (folder / "data" / "meta.json").write_text("{}")
    monkeypatch.setattr(site, "LAST", tmp_path / "last.json")
    monkeypatch.setattr(site, "LIVE_WAIT_S", 0.2)
    monkeypatch.setattr(site.time, "sleep", lambda s: None)
    return folder


def test_digests_are_sha1_of_every_file_with_leading_slash_paths(dist):
    digest = site.digests(dist)
    assert set(digest) == {"/index.html", "/_headers", "/data/meta.json"} and all(len(d) == 40 for d in digest.values())


def test_publish_uploads_only_what_netlify_lacks_and_records_the_deploy(dist, monkeypatch):
    calls = []
    monkeypatch.setattr(site.httpx, "get", lambda url, **kw: REAL_CLIENT(transport=fake_netlify(calls)).get(url))
    monkeypatch.setattr(site.httpx, "Client", lambda **kw: REAL_CLIENT(**{**kw, "transport": fake_netlify(calls, has_files=("/index.html",))}))
    deploy_id = site.publish(dist, "https://site.test", "S", "token", 4450)
    assert deploy_id == "new-deploy"
    puts = [p for m, p in calls if m == "PUT"]
    assert sorted(puts) == ["/api/v1/deploys/new-deploy/files/_headers", "/api/v1/deploys/new-deploy/files/data/meta.json"]  # index.html was already there
    assert json.loads(site.LAST.read_text())["previous"] == "old-deploy"


def test_publish_restores_the_previous_deploy_when_the_live_check_fails(dist, monkeypatch):
    calls = []
    monkeypatch.setattr(site.httpx, "get", lambda url, **kw: REAL_CLIENT(transport=fake_netlify(calls, served=4000)).get(url))
    monkeypatch.setattr(site.httpx, "Client", lambda **kw: REAL_CLIENT(**{**kw, "transport": fake_netlify(calls, served=4000)}))
    with pytest.raises(RuntimeError, match="previous deploy old-deploy is restored"):
        site.publish(dist, "https://site.test", "S", "token", 4450)
    assert ("POST", "/api/v1/sites/S/deploys/old-deploy/restore") in calls
    assert not site.LAST.exists()


def test_refresh_does_nothing_without_a_site_url_and_skips_a_current_site(monkeypatch, tmp_path):
    monkeypatch.delenv("SITE_URL", raising=False)
    assert site.refresh() == "skipped"
    monkeypatch.setenv("SITE_URL", "https://site.test")
    monkeypatch.setattr(site, "build_data", lambda out: (out.mkdir(parents=True), (out / "meta.json").write_text(json.dumps(meta()))))
    monkeypatch.setattr(site, "data_problems", lambda folder: [])
    monkeypatch.setattr(site.httpx, "get", lambda url, **kw: httpx.Response(200, json=meta(), request=httpx.Request("GET", url)))
    assert site.refresh() == "current"
    monkeypatch.setattr(site, "build_data", lambda out: (out.mkdir(parents=True), (out / "meta.json").write_text(json.dumps(meta(listings_total=4450)))))
    assert site.refresh(deploy=False) == "dry-run"


def test_refresh_refuses_a_bad_build_before_touching_the_site(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://site.test")
    monkeypatch.setattr(site, "build_data", lambda out: (out.mkdir(parents=True), (out / "meta.json").write_text(json.dumps(meta(listings_total=3000)))))
    monkeypatch.setattr(site, "data_problems", lambda folder: [])
    monkeypatch.setattr(site.httpx, "get", lambda url, **kw: httpx.Response(200, json=meta(), request=httpx.Request("GET", url)))
    with pytest.raises(RuntimeError, match="not published: fewer listings"):
        site.refresh()
