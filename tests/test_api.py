import pytest
from fastapi.testclient import TestClient

from src.serving.api import create_app
from src.serving.estimator import House, OutsideArea

BODY = {"lat": -6.26, "lon": 106.81, "land_area": 120, "building_area": 150, "bedrooms": 3, "bathrooms": 2}


class Stub:
    info = {"trained_rows": 1, "holdout_median_error": 0.227}

    def __init__(self):
        self.seen: list[House] = []

    def estimate(self, house: House) -> dict:
        if house.lat > -6.0:
            raise OutsideArea("The point is outside Jabodetabek.")
        self.seen.append(house)
        return {"price_idr": 1}


@pytest.fixture
def stub():
    return Stub()


@pytest.fixture
def client(stub, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "5")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://example.app")
    with TestClient(create_app(stub)) as c:
        yield c


def test_health_and_model(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/model").json()["trained_rows"] == 1


def test_estimate_passes_the_house_to_the_estimator(client, stub):
    response = client.post("/estimate", json={**BODY, "floors": 2, "notes": "Rumah baru", "specs": {"electricity_va": 3500, "carport": None}})
    assert response.status_code == 200
    house = stub.seen[0]
    assert (house.land_area, house.floors, house.notes, house.specs) == (120, 2, "Rumah baru", {"spec_electricity_va": 3500})


@pytest.mark.parametrize("change", [{"land_area": 5}, {"land_area": 99_999}, {"bedrooms": 0}, {"bathrooms": 20}, {"lat": 40}, {"lon": 0},
                                    {"notes": "x" * 2001}, {"floors": 0}, {"specs": {"furnished_level": 5}}])
def test_out_of_range_inputs_are_rejected(client, change):
    assert client.post("/estimate", json={**BODY, **change}).status_code == 422


def test_missing_required_field_is_rejected(client):
    assert client.post("/estimate", json={k: v for k, v in BODY.items() if k != "land_area"}).status_code == 422


def test_point_outside_the_area_is_a_422_with_a_message(client):
    response = client.post("/estimate", json={**BODY, "lat": -5.9})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "outside_area" and "outside" in response.json()["detail"]["message"]


def test_rate_limit_per_client(client):
    codes = [client.post("/estimate", json=BODY, headers={"x-forwarded-for": "1.2.3.4"}).status_code for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2
    assert client.post("/estimate", json=BODY, headers={"x-forwarded-for": "5.6.7.8"}).status_code == 200


def test_cors_only_for_the_allowed_origin(client):
    allowed = client.options("/estimate", headers={"origin": "https://example.app", "access-control-request-method": "POST"})
    other = client.options("/estimate", headers={"origin": "https://evil.example", "access-control-request-method": "POST"})
    assert allowed.headers.get("access-control-allow-origin") == "https://example.app"
    assert "access-control-allow-origin" not in other.headers


def test_docs_are_off_by_default(client):
    assert client.get("/docs").status_code == 404


@pytest.mark.parametrize("field", ["lat", "lon", "land_area", "building_area", "floors"])
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_are_refused_not_a_server_error(client, field, bad):
    body = '{"lat": -6.26, "lon": 106.81, "land_area": 120, "building_area": 150, "bedrooms": 3, "bathrooms": 2, "floors": 2}'.replace(f'"{field}": ', f'"{field}": {bad}, "_": ', 1)
    assert client.post("/estimate", content=body, headers={"content-type": "application/json"}).status_code == 422


def test_a_huge_body_is_refused_before_it_is_read(client, stub):
    assert client.post("/estimate", content=b"x" * 40_000, headers={"content-type": "application/json"}).status_code == 413
    streamed = (chunk for chunk in [b'{"notes": "', b"x" * 20_000, b"x" * 20_000, b'"}'])  # no Content-Length: the limit applies while it streams in
    assert client.post("/estimate", content=streamed, headers={"content-type": "application/json"}).status_code == 413
    assert stub.seen == []
    assert client.post("/estimate", json=BODY).status_code == 200  # a normal request still passes


def test_responses_carry_security_headers(client):
    headers = client.post("/estimate", json=BODY).headers
    assert headers["x-content-type-options"] == "nosniff" and headers["cache-control"] == "no-store"


def test_global_cap_holds_even_when_every_request_claims_a_new_address(monkeypatch, stub):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "100")
    monkeypatch.setenv("GLOBAL_LIMIT_PER_MINUTE", "3")
    with TestClient(create_app(stub)) as c:
        codes = [c.post("/estimate", json=BODY, headers={"x-forwarded-for": f"198.51.100.{i}"}).status_code for i in range(6)]
    assert codes == [200, 200, 200, 429, 429, 429]
