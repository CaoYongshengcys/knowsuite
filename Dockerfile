FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

# ffmpeg for video module (audio/frame extraction)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN mkdir -p /data/videos /data/video_md
VOLUME ["/data"]
EXPOSE 8100

WORKDIR /app/backend
ENV DATA_DIR=/data
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
