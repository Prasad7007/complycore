FROM python:3.11-slim

WORKDIR /loadtest

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py stats.py locustfile.py ./

# Fixtures and .env are mounted at runtime (not baked into the image).
CMD ["locust", "-f", "locustfile.py"]
