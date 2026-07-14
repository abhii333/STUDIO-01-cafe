FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

EXPOSE 5000

# 1 worker + 16 threads: a single worker keeps the in-memory rate limiter
# state consistent (exact 5/min) while threads handle concurrent requests.
# No long-lived connections — live tracking uses short polling from the frontend.
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "16", "--timeout", "120"]
