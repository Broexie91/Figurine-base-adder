FROM lscr.io/linuxserver/blender:latest

# Extra deps: fonts voor text, GL libs voor rendering (indien nodig)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    libfreetype6 libfontconfig1 \
    libgl1 libxi6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installeer Python deps (fastapi etc.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer je code
COPY main.py blender_process.py ./

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
