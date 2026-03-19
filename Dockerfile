FROM cadquery/cadquery:latest

WORKDIR /app

# Install additional Python packages needed for the API
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    requests \
    trimesh \
    numpy

COPY . /app

# Railway uses port 8080 or the PORT environment variable
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
