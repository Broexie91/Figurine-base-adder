FROM python:3.11-slim

WORKDIR /app

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libxrender1 \
    libxkbcommon0 \
    libdbus-1-3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Upgrade pip first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install CadQuery (comes with pre-built wheels including cascadio)
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
