FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN apt-get update && apt-get install -y curl
RUN pip install --no-cache-dir flask waitress requests psutil

EXPOSE 3010

CMD ["python", "ollama_monitor.py"]
