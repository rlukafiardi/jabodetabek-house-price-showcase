"""FastAPI service: POST /estimate returns the price estimate with ranges for one house, GET /model the model's facts, GET /health.
Settings come from the environment: MODEL_DIR (default serving/model), ALLOWED_ORIGINS (comma-separated browser origins, none by
default), RATE_LIMIT_PER_MINUTE, ENABLE_DOCS=1 to serve /docs. Run: uv run uvicorn src.serving.api:app --port 8080"""

import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import ROOT
from src.modeling.split import LAT_RANGE, LON_RANGE, MAX_ROOMS
from src.serving.estimator import Estimator, House, OutsideArea

RATE_WINDOW_S = 60
MAX_TRACKED_CLIENTS = 10_000


class SpecsIn(BaseModel):
    """Optional details; leave out what is not known."""
    electricity_va: float | None = Field(None, ge=450, le=40_000)
    carport: int | None = Field(None, ge=0, le=10)
    car_access: int | None = Field(None, ge=0, le=10)
    garage: int | None = Field(None, ge=0, le=10)
    maid_rooms: int | None = Field(None, ge=0, le=5)
    furnished_level: int | None = Field(None, ge=0, le=2, description="0 not furnished, 1 semi, 2 furnished")
    water_pam: int | None = Field(None, ge=0, le=1, description="1 piped water (PAM), 0 groundwater")


class HouseIn(BaseModel):
    lat: float = Field(ge=LAT_RANGE[0], le=LAT_RANGE[1])
    lon: float = Field(ge=LON_RANGE[0], le=LON_RANGE[1])
    land_area: float = Field(ge=15, le=5000, description="m²")
    building_area: float = Field(ge=15, le=3000, description="m², summed over all floors")
    bedrooms: int = Field(ge=1, le=MAX_ROOMS)
    bathrooms: int = Field(ge=1, le=MAX_ROOMS)
    floors: float | None = Field(None, ge=1, le=6)
    notes: str = Field("", max_length=2000, description="Free text like a listing description: furnished, new, gated, ...")
    specs: SpecsIn = SpecsIn()

    def to_house(self) -> House:
        return House(self.lat, self.lon, self.land_area, self.building_area, self.bedrooms, self.bathrooms, self.floors, self.notes,
                     {f"spec_{k}": v for k, v in self.specs.model_dump().items() if v is not None})


class RateLimiter:
    """At most `limit` requests per client per minute, counted in memory (one or two instances: good enough to stop a loop)."""
    def __init__(self, limit: int):
        self.limit, self.hits, self.lock = limit, defaultdict(deque), threading.Lock()

    def __call__(self, request: Request) -> None:
        forwarded = request.headers.get("x-forwarded-for", "")
        client = forwarded.split(",")[-1].strip() if forwarded else (request.client.host if request.client else "unknown")  # Cloud Run appends the real client last
        now = time.monotonic()
        with self.lock:
            if len(self.hits) > MAX_TRACKED_CLIENTS:
                self.hits.clear()
            window = self.hits[client]
            while window and now - window[0] > RATE_WINDOW_S:
                window.popleft()
            if len(window) >= self.limit:
                raise HTTPException(429, "Too many requests, try again in a minute.", headers={"Retry-After": str(RATE_WINDOW_S)})
            window.append(now)


def create_app(estimator: Estimator | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.estimator = estimator or Estimator(Path(os.environ.get("MODEL_DIR", ROOT / "serving" / "model")))
        yield

    app = FastAPI(title="Jabodetabek house price estimate", lifespan=lifespan, docs_url="/docs" if os.environ.get("ENABLE_DOCS") else None,
                  redoc_url=None, openapi_url="/openapi.json" if os.environ.get("ENABLE_DOCS") else None)
    origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["content-type"])
    limiter = RateLimiter(int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30")))
    lock = threading.Lock()  # one estimate at a time: it takes about 50 ms and the spatial indexes are shared

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/model")
    def model(request: Request) -> dict:
        return request.app.state.estimator.info

    @app.post("/estimate", dependencies=[Depends(limiter)])
    def estimate(house: HouseIn, request: Request) -> dict:
        try:
            with lock:
                return request.app.state.estimator.estimate(house.to_house())
        except OutsideArea as error:
            raise HTTPException(422, str(error)) from error

    return app


app = create_app()
