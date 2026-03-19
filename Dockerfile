FROM blenderkit/headless-blender:latest

# Extra libs voor fonts + GL (voor text en Meshy import)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    libfreetype6 libfontconfig1 \
    libgl1 libxi6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Jouw code
COPY main.py blender_process.py ./

# Blender staat in deze image op /home/headless/blender
RUN ln -s /home/headless/blender/blender /usr/local/bin/blender

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
