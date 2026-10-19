FROM python:3.11-slim

# System dependencies for OpenCV, PyMuPDF, and text rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose port (default 8000)
EXPOSE 8000

ENV PORT=8000
CMD ["uvicorn", "web_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
