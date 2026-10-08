FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RG_TELEGRAM_STATE_DIR=/state
WORKDIR /srv/telegram_reader
RUN pip install --no-cache-dir fastmcp==4.0.11
COPY status_reader.py app.py smoke.py ./
EXPOSE 18767
CMD ["python", "app.py"]
