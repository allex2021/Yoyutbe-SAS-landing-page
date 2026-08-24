# Use official lightweight Python image
FROM python:3.11-slim

# Install system dependencies (including ffmpeg and curl)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (needed for yt-dlp JavaScript decryption challenges)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source files
COPY . .

# Create output directory
RUN mkdir -p output

# Expose the Flask port (Render/Railway default dynamic PORT)
EXPOSE 8080

# Start the Flask web app server
CMD ["python", "app.py"]
