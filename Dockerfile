FROM blenderkit/headless-blender:blender-5.1

# Extra deps voor fonts en GL (nodig voor text en Meshy imports)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    libfreetype6 libfontconfig1 \
    libgl1 libxi6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py blender_process.py ./

# Blender path in deze image is /home/headless/blenders/5.1/blender (of vergelijkbaar)
# Maak een symlink voor eenvoud
RUN ln -s /home/headless/blenders/5.1/blender /usr/local/bin/blender

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
