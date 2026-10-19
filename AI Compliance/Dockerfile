FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies + LibreOffice (headless)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    libxrender1 \
    libxext6 \
    libsm6 \
    libjpeg62-turbo \
    zlib1g \
    libreoffice-common \
    libreoffice-core \
    libreoffice-impress \
    libreoffice-writer \
    python3-uno \
    ure \
    fonts-dejavu \
    fonts-liberation \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better layer caching)
COPY requirements.txt .

# Remove Windows-only deps + install Python deps
RUN pip install --no-cache-dir --upgrade pip && \
    grep -v "^pywin32==" requirements.txt > /tmp/requirements.docker.txt && \
    pip install --no-cache-dir -r /tmp/requirements.docker.txt

# Copy app code
COPY . .

EXPOSE 8052

# Run FastAPI
CMD ["uvicorn", "apis.main:app", "--host", "0.0.0.0", "--port", "8052"]

