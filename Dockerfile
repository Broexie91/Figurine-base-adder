FROM condaforge/miniforge3:latest

WORKDIR /app

# Install cadquery and all dependencies including cascadio
RUN mamba install -y -c conda-forge \
    cadquery \
    pyocc \
    trimesh \
    fastapi \
    uvicorn \
    requests \
    numpy && \
    mamba clean --all --yes

COPY . /app

# Railway uses port 8080 or the PORT environment variable
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
