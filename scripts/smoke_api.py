"""Smoke test of the built API image: start the app (loads the model and the layers), check /health, /model and one estimate."""

from fastapi.testclient import TestClient

from src.serving.api import app

house = {"lat": -6.2615, "lon": 106.8106, "land_area": 150, "building_area": 200, "bedrooms": 4, "bathrooms": 3, "floors": 2, "notes": "rumah mewah cluster"}
with TestClient(app) as client:
    print("health", client.get("/health").json())
    print("model", client.get("/model").json())
    response = client.post("/estimate", json=house)
    print("estimate", response.status_code, response.json())
    assert response.status_code == 200 and response.json()["price_idr"] > 1e9
