# Gebruik officiële Python 3.11 slim variant (licht, maar met alles wat nodig is)
FROM python:3.11-slim-bookworm

# Installeer system dependencies die Blender + GL libs nodig hebben
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    libgl1 \
    libxi6 \
    libxrender1 \
    libxkbcommon0 \
    libsm6 \
    libice6 \
    libglib2.0-0 \
    libfreetype6 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Download en installeer Blender 5.1.0 (headless versie)
RUN wget https://download.blender.org/release/Blender5.1/blender-5.1.0-linux-x64.tar.xz -O /tmp/blender.tar.xz && \
    tar -xJf /tmp/blender.tar.xz -C /opt/ && \
    mv /opt/blender-5.1.0-linux-x64 /opt/blender && \
    ln -s /opt/blender/blender /usr/local/bin/blender && \
    rm /tmp/blender.tar.xz

WORKDIR /app

# Kopieer en installeer Python dependencies (geen externally-managed issue hier)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer je app code
COPY main.py blender_process.py ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
