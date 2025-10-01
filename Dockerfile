# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# system deps (build-essential for python-levenshtein)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev && rm -rf /var/lib/apt/lists/*

# copy project
COPY . /app

# install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# expose nothing; runs as service
CMD ["python", "main.py"]
