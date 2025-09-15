# 1. Start with a lightweight Python base image
FROM python:3.11-slim

# 2. Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. Set a working directory inside the container
WORKDIR /app

# 4. Copy and install dependencies first (for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your application code into the container
COPY . .

# 6. Expose the port the app runs on
EXPOSE 8000

# 7. Make our startup script executable and run it
# This script will run migrations and then start the server
COPY ./render-build.sh /app/render-build.sh
RUN chmod +x /app/render-build.sh
CMD ["/app/render-build.sh"]