FROM python:3.11-slim

WORKDIR /app

# Sistem bağımlılıkları (Prisma ve PostgreSQL için)
RUN apt-get update && apt-get install -y openssl libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Prisma Client üretimi
RUN prisma generate

# Python'un 'app' klasörünü görmesini sağla
ENV PYTHONPATH=/app

EXPOSE 8000

# app.main içindeki 'app' nesnesini çağırıyoruz
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]