FROM mambaorg/micromamba:latest

COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
WORKDIR /app

# Install all dependencies (including graphics libraries) via conda/mamba
RUN micromamba install -y -n base -c conda-forge \
    cadquery \
    trimesh \
    fastapi \
    uvicorn \
    requests \
    numpy \
    libglu \
    libxkbcommon \
    && micromamba clean --all --yes

# Railway uses port 8080 or the PORT environment variable
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
