FROM cadquery/cadquery:latest

WORKDIR /app

# Install Python dependencies via pip
RUN pip install --no-cache-dir --upgrade \
    fastapi \
    uvicorn[standard] \
    requests \
    trimesh \
    numpy

COPY . /app

# Expose port 8080
EXPOSE 8080

# Railway uses port 8080 or the PORT environment variable
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
