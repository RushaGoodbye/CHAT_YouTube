FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rg_remote_mcp ./rg_remote_mcp
ENV PYTHONUNBUFFERED=1
CMD ["python","-m","rg_remote_mcp.server"]
