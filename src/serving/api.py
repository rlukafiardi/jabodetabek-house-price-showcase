"""FastAPI service: POST /estimate returns the price estimate with ranges for one house, GET /model the model's facts, GET /health.
Settings come from the environment: MODEL_DIR (default serving/model), ALLOWED_ORIGINS (comma-separated browser origins, none by
default), RATE_LIMIT_PER_MINUTE (per client), GLOBAL_LIMIT_PER_MINUTE (all clients together: the cap that keeps a public free-tier service inside
its free quota), ENABLE_DOCS=1 to serve /docs. Run: uv run uvicorn src.serving.api:app --port 8080"""

import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.config import ROOT
from src.modeling.split import LAT_RANGE, LON_RANGE, MAX_ROOMS
from src.serving.estimator import Estimator, House, OutsideArea

RATE_WINDOW_S = 60
MAX_TRACKED_CLIENTS = 10_000
MAX_BODY_BYTES = 32 * 1024  # a request is about 1 KB; notes of 2,000 characters are at most 8 KB in UTF-8. Anything bigger is not a house.


class SpecsIn(BaseModel):
    """Optional details; leave out what is not known."""
    electricity_va: float | None = Field(None, allow_inf_nan=False, ge=450, le=40_000)
    carport: int | None = Field(None, ge=0, le=10)
    car_access: int | None = Field(None, ge=0, le=10)
    garage: int | None = Field(None, ge=0, le=10)
    maid_rooms: int | None = Field(None, ge=0, le=5)
    furnished_level: int | None = Field(None, ge=0, le=2, description="0 not furnished, 1 semi, 2 furnished")
    water_pam: int | None = Field(None, ge=0, le=1, description="1 piped water (PAM), 0 groundwater")


class HouseIn(BaseModel):
    lat: float = Field(allow_inf_nan=False, ge=LAT_RANGE[0], le=LAT_RANGE[1])
    lon: float = Field(allow_inf_nan=False, ge=LON_RANGE[0], le=LON_RANGE[1])
    land_area: float = Field(allow_inf_nan=False, ge=15, le=5000, description="m²")
    building_area: float = Field(allow_inf_nan=False, ge=15, le=3000, description="m², summed over all floors")
    bedrooms: int = Field(ge=1, le=MAX_ROOMS)
    bathrooms: int = Field(ge=1, le=MAX_ROOMS)
    floors: float | None = Field(None, allow_inf_nan=False, ge=1, le=6)
    notes: str = Field("", max_length=2000, description="Free text like a listing description: furnished, new, gated, ...")
    specs: SpecsIn = SpecsIn()

    def to_house(self) -> House:
        return House(self.lat, self.lon, self.land_area, self.building_area, self.bedrooms, self.bathrooms, self.floors, self.notes,
                     {f"spec_{k}": v for k, v in self.specs.model_dump().items() if v is not None})


class RateLimiter:
    """At most `limit` requests per client per minute and `global_limit` for everyone together, counted in memory (one instance: good enough to stop
    a loop, and the global cap keeps the month's total under the free quota however many addresses a caller uses)."""
    def __init__(self, limit: int, global_limit: int):
        self.limit, self.global_limit = limit, global_limit
        self.hits, self.total, self.lock = defaultdict(deque), deque(), threading.Lock()

    def __call__(self, request: Request) -> None:
        forwarded = request.headers.get("x-forwarded-for", "")
        client = forwarded.split(",")[-1].strip() if forwarded else (request.client.host if request.client else "unknown")  # Cloud Run appends the real client last
        now = time.monotonic()
        with self.lock:
            if len(self.hits) > MAX_TRACKED_CLIENTS:
                self.hits.clear()
            window = self.hits[client]
            for hits in (window, self.total):
                while hits and now - hits[0] > RATE_WINDOW_S:
                    hits.popleft()
            if len(window) >= self.limit or len(self.total) >= self.global_limit:
                raise HTTPException(429, "Too many requests, try again in a minute.", headers={"Retry-After": str(RATE_WINDOW_S)})
            window.append(now)
            self.total.append(now)


class BodyLimit:
    """Refuse a request body over MAX_BODY_BYTES before it is read into memory (by its Content-Length, or while it streams in)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length")
        too_big = JSONResponse({"detail": "Request body too large."}, status_code=413)
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return await too_big(scope, receive, send)
        received, rejected = 0, False

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            received += len(message.get("body", b"")) if message["type"] == "http.request" else 0
            if received > MAX_BODY_BYTES and not rejected:
                rejected = True
                await too_big(scope, receive, send)  # answer now, then tell the app the client is gone so it stops reading
            return {"type": "http.disconnect"} if rejected else message

        async def guarded_send(message):
            if not rejected:  # whatever the app says after the refusal (it sees a dropped connection) is not sent
                await send(message)

        await self.app(scope, limited_receive, guarded_send)


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
    limiter = RateLimiter(int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30")), int(os.environ.get("GLOBAL_LIMIT_PER_MINUTE", "30")))  # 30 a minute is at most 1.3 million a month: under the free 2 million requests, and under 180,000 vCPU-seconds while a request takes under 0.13 s (see docs/deploy-security.md)
    lock = threading.Lock()  # one estimate at a time: it takes about 50 ms and the spatial indexes are shared

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        """Say which field is wrong and why, without echoing the input back (a NaN in it would also crash the JSON encoder: a 500 instead of a 422)."""
        return JSONResponse({"detail": [{"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]}, status_code=422)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

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
            raise HTTPException(422, {"code": "outside_area", "message": str(error)}) from error

    return BodyLimit(app)


app = create_app()
