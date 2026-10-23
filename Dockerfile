FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates libgssapi-krb5-2 unixodbc \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -o /tmp/microsoft.deb \
    && dpkg -i /tmp/microsoft.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -f /tmp/microsoft.deb \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-render.txt ./
RUN pip install -r requirements-render.txt
COPY . .
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/instance \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 10000
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
