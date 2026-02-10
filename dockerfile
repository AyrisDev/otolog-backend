FROM python:3.11-slim

WORKDIR /app

# Sistem bağımlılıkları (Prisma için gerekli)
RUN apt-get update && apt-get install -y openssl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hata veren kısım burasıydı, URL'i build aşamasında tanıtıyoruz
ARG DATABASE_URL="postgres://postgres:6UuYjVZ13ZKfmgKRIsXiCqNjLriAkvugGG9awYqM4BXo78Sg39JypbyNgV72K0zY@65.109.236.58:5433/postgres"
ENV DATABASE_URL=$DATABASE_URL

# Şimdi hata vermeden client üretecektir
RUN prisma generate

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]