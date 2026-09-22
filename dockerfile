FROM python:3.12-slim
ENV POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry lock --no-interaction \
    && poetry install --no-interaction --no-ansi \
    && chmod +x entrypoint.sh

EXPOSE 8000
CMD ["./entrypoint.sh"]
