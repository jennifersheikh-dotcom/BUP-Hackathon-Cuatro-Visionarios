FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home appuser
COPY gridwise ./gridwise
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)"
CMD ["python", "-m", "gridwise.server"]
