FROM python:3.11-slim

WORKDIR /app

# Install only the essential system libraries that actually exist in Debian slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libxrender1 \
    libxkbcommon0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Upgrade pip first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install CadQuery with pre-built wheels
RUN pip install --no-cache-dir \
    cadquery==2.4.0 \
    trimesh \
    fastapi \
    uvicorn \
    requests \
    numpy

COPY . /app

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
