FROM python:3.11-slim-bookworm

# System deps voor Blender (GL, fonts, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates \
    libgl1 libxi6 libxrender1 libxkbcommon0 libsm6 libice6 libglib2.0-0 \
    libfreetype6 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Blender download & install
RUN wget https://download.blender.org/release/Blender5.1/blender-5.1.0-linux-x64.tar.xz -O /tmp/blender.tar.xz && \
    tar -xJf /tmp/blender.tar.xz -C /opt/ && \
    mv /opt/blender-5.1.0-linux-x64 /opt/blender && \
    ln -s /opt/blender/blender /usr/local/bin/blender && \
    rm /tmp/blender.tar.xz

WORKDIR /app

# Creëer & activeer venv → lost externally-managed op
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Upgrade pip en installeer deps in venv
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Kopieer code
COPY main.py blender_process.py ./

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
