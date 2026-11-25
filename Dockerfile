FROM python:3.15.1-slim@sha256:533b0b2f9b5d46fd097091cf826f27902f1d6c3bca714b6dc74551356aa97a51
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PVZ_HOST=0.0.0.0 PVZ_PORT=8080 PVZ_DATA=/var/lib/atlas PVZ_DEMO=1
WORKDIR /srv/atlas
RUN groupadd --gid 10001 atlas && useradd --uid 10001 --gid atlas --no-create-home atlas \
    && install -d -o atlas -g atlas /var/lib/atlas
COPY app/ ./
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=2).close()"]
CMD ["python", "serve.py"]
