FROM mambaorg/micromamba:latest

# Switch to root to install system packages
USER root

# Install system dependencies required by CadQuery and graphics libraries
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libxrender1 \
    libxkbcommon0 \
    libdbus-1-3 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Switch back to mamba user
USER $MAMBA_USER

COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
WORKDIR /app

RUN micromamba install -y -n base -c cadquery -c conda-forge \
    cadquery \
    trimesh \
    fastapi \
    uvicorn \
    requests \
    numpy \
    && micromamba clean --all --yes

# Railway uses port 8080 or the PORT environment variable
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
