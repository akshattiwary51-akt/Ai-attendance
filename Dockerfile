# SnapClass: Streamlit app. Supabase (Postgres + Auth) is external; see README "Deployment".
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install -r requirements.txt
# Only needed for ASSISTANT_MODE=llm; remove this line to keep the image smaller.
RUN pip install "anthropic>=0.40"

FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    STREAMLIT_SERVER_PORT=8501 STREAMLIT_SERVER_ADDRESS=0.0.0.0
# libsndfile/ffmpeg: audio decoding for the voice model. libgl/glib: image libraries used by onnxruntime/pillow.
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 ffmpeg libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 snap
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=snap:snap . .
USER snap
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "app.py"]
