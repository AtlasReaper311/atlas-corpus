FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Non-root; /srv/docs is a read-only mount and /srv/data is the query
# log volume. The mountpoint is created before the chown so the named
# volume initialises with corpus ownership instead of root; the same
# ownership trap as the Ollama model dir, closed at build time.
RUN useradd --create-home --uid 10001 corpus \
    && mkdir -p /srv/data \
    && chown -R corpus /srv
USER corpus

EXPOSE 8092
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8092"]
