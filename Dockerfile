FROM python:3.10.12

# Install Node.js, npm, git, and Chromium in a single RUN command
RUN apt-get update && apt-get install -y nodejs npm git chromium && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install single-file-cli
RUN npm install -g single-file-cli

# Set working directory
WORKDIR /app

# Copy only requirements.txt first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Set environment variable
ENV PORT 8080

# Command to run the application
CMD uvicorn main:app --host=0.0.0.0 --port=$PORT