FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    wget python3 python3-pip \
    libgl1 libxi6 libxrender1 libxkbcommon0 libsm6 libice6 libglib2.0-0 \
    libfreetype6 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Blender 5.1.0 (nieuwste versie maart 2026)
RUN wget https://download.blender.org/release/Blender5.1/blender-5.1.0-linux-x64.tar.xz -O /tmp/blender.tar.xz && \
    tar -xJf /tmp/blender.tar.xz -C /opt/ && \
    mv /opt/blender-5.1.0-linux-x64 /opt/blender && \
    ln -s /opt/blender/blender /usr/local/bin/blender && \
    rm /tmp/blender.tar.xz

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY main.py blender_process.py ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
