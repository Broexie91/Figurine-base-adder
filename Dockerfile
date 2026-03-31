FROM ubuntu:24.04

# Voorkom interactieve prompts
ENV DEBIAN_FRONTEND=noninteractive

# Systeem packages + xz-utils (nodig voor Blender .tar.xz)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    xvfb \
    python3-numpy \
    libgl1 \
    libglib2.0-0 \
    libxrender1 \
    libxkbcommon0 \
    libsm6 \
    libxi6 \
    libxext6 \
    libxfixes3 \
    libxxf86vm1 \
    wget \
    xz-utils \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Officiële Blender 5.1 installeren (stabiel in headless mode)
ARG BLENDER_VERSION=5.1.0
RUN wget -q https://download.blender.org/release/Blender${BLENDER_VERSION%.*}/blender-${BLENDER_VERSION}-linux-x64.tar.xz -O /tmp/blender.tar.xz && \
    mkdir -p /opt/blender && \
    tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 && \
    ln -s /opt/blender/blender /usr/local/bin/blender && \
    rm /tmp/blender.tar.xz

# Install the 3D Print Toolbox as a Blender Extension (4.2+ format, id: print3d_toolbox).
# The zip unpacks directly to the extension root, so we extract into the named subfolder.
ARG EXT_DIR=/root/.config/blender/5.1/extensions/user_default/print3d_toolbox
COPY add-on-print3d-toolbox-v1.3.3.zip /tmp/print3d.zip
RUN mkdir -p ${EXT_DIR} && \
    unzip -q /tmp/print3d.zip -d ${EXT_DIR} && \
    rm /tmp/print3d.zip

ENV BLENDER_SYSTEM_PYTHON=1

# Werkdirectory en virtual environment
WORKDIR /app

RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Je code
COPY main.py blender_process.py ./

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
