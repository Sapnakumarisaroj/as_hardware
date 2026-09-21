# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app

# ---- development image (hot reload, test tooling) ----
FROM base AS dev
COPY requirements/ requirements/
RUN pip install -r requirements/dev.txt
COPY . .
USER app
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]

# ---- production image ----
FROM base AS prod
COPY requirements/ requirements/
RUN pip install -r requirements/prod.txt
COPY . .
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=sqlite:////tmp/build.db ALLOW_MOCK_PAYMENTS_IN_PROD=true python manage.py collectstatic --noinput
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
