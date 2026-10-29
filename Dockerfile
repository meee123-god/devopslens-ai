# Dockerfile for DevOpsLens AI Streamlit Frontend
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose Streamlit default port
EXPOSE 8501

# Health check probe
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Start Streamlit frontend
ENTRYPOINT ["streamlit", "run", "frontend/dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]
