# Daily bond-futures monitor runner image.
# Build:  docker build -t bond-futures-monitor .
# Run:    docker run --rm --env-file .env -v $(pwd)/data:/app/data \
#             -v $(pwd)/reports_output:/app/reports_output bond-futures-monitor
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=Asia/Shanghai

WORKDIR /app

# Mainland mirrors make builds on Aliyun ECS fast; default stays PyPI.
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

# Install dependencies first so code edits don't bust the pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bond_futures_monitor/ bond_futures_monitor/

# data/ and reports_output/ are volume mounts supplied at run time.
ENTRYPOINT ["python", "-m", "bond_futures_monitor.cli"]
CMD ["run", "--date", "today"]
