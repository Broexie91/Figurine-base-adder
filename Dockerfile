# Dockerfile for Figurine-base-adder\n\nFROM python:3.8-slim\n\n# Install system dependencies for CadQuery graphics libraries\nRUN apt-get update && \
    apt-get install -y libgl1 libxrender1 libxkbcommon0 libdbus-1-3 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*\n\n# Set the working directory\nWORKDIR /app\n\n# Copy the current directory contents into the container at /app\nCOPY . /app\n\n# Install Python packages\nRUN pip install --no-cache-dir numpy\n\n# Run the application\nCMD ["python", "your_script.py"]