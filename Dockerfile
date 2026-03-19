FROM ubuntu:24.04

# Prevent interactive prompts during tzdata/apt-get
ENV DEBIAN_FRONTEND=noninteractive

# Install Python, pip, Blender, and Xvfb all from official Ubuntu repositories
# This avoids extracting giant .tar.xz files which causes Out Of Memory on Hobby plans
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    blender \
    xvfb \
    python3-numpy \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create a virtual environment and add it to PATH
RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY main.py blender_process.py ./

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
