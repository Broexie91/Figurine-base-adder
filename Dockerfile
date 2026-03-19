# Stage 1: Download en pak Blender uit (zware stap, maar geïsoleerd)
FROM ubuntu:24.04 AS downloader

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN wget https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz -O /tmp/blender.tar.xz && \
    mkdir -p /opt/blender && \
    tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 && \
    rm /tmp/blender.tar.xz

# Stage 2: Final lichte runtime image
FROM python:3.11-slim-bookworm

# Kopieer Blender uit stage 1
COPY --from=downloader /opt/blender /opt/blender

# Symlink voor gemakkelijke call
RUN ln -s /opt/blender/blender /usr/local/bin/blender

# System libs (GL, fonts voor text/materials)
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb libgl1 libxi6 libxrender1 libxkbcommon0 libsm6 libice6 libglib2.0-0 \
    libfreetype6 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Venv voor pip (lost externally-managed op)
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY main.py blender_process.py ./

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
