FROM ghcr.io/ggml-org/llama.cpp:server-cuda@sha256:6b0bf4974521b2c16a498c7dd0715f4eb077725f1483e0ee0f617679005b1e1f

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/tep

COPY experiments/tep/local_llm/requirements.lock /opt/tep/requirements.lock
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip==25.1.1 \
    && /opt/venv/bin/python -m pip install --no-cache-dir -r /opt/tep/requirements.lock

COPY experiments/tep/local_llm/src /opt/tep/src
COPY experiments/tep/local_llm/config /opt/tep/config
COPY experiments/tep/local_llm/tests /opt/tep/tests

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/opt/tep/src" \
    PYTHONUNBUFFERED="1" \
    LD_LIBRARY_PATH="/app" \
    LLAMA_SERVER_BIN="/app/llama-server"

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin experiment \
    && mkdir -p /results /data/normal /data/test /models \
    && chown -R experiment:experiment /results /opt/tep

USER experiment

ENTRYPOINT ["/opt/venv/bin/python", "-m", "tep_local.cli"]
CMD ["--help"]
