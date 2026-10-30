# Model API. Build context: the repo with the bundle built by `uv run python -m src.serving.bundle` (serving/model, serving/data).
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libexpat1 && rm -rf /var/lib/apt/lists/*  # OpenMP (XGBoost, scikit-learn) and expat (rasterio)
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# One layer, no cache: xgboost on Linux pulls 305 MB of NVIDIA NCCL libraries, so swap in the 6 MB CPU-only build of the same version
# before the layer closes (a later RUN would leave the big files inside the image; the registry free tier is 0.5 GB)
ENV UV_NO_CACHE=1
RUN uv sync --frozen --no-dev --group serving --no-install-project \
 && uv pip uninstall --python .venv/bin/python xgboost nvidia-nccl-cu13 \
 && uv pip install --python .venv/bin/python --no-deps xgboost-cpu==3.4.1
COPY src ./src
COPY serving/data ./data
COPY serving/model ./model
ENV MODEL_DIR=/app/model PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn src.serving.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
