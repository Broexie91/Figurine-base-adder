FROM mambaorg/micromamba:latest

COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
WORKDIR /app

RUN micromamba install -y -n base -c cadquery -c conda-forge \
    cadquery \
    trimesh \
    fastapi \
    uvicorn \
    requests \
    && micromamba clean --all --yes

# Railway gebruikt poort 8080 of de PORT omgevingsvariabele
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
