# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
#
# MedAgentRx container. Runs as UID 10001, works with --read-only and a
# tmpfs on /tmp, and needs no shell at run time.
#   docker build -t medagentrx .
#   docker run --rm --read-only --tmpfs /tmp medagentrx

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.15@sha256:62f8c047d0a0e9ece6b53fc63df902585a67a47a7f318ddec4a37db586edc8e3 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/medagentrx
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv sync --frozen --no-dev --extra web --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra web --no-editable

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ARG VERSION=0.1.0.dev0
LABEL org.opencontainers.image.title="MedAgentRx" \
      org.opencontainers.image.description="Every model update, by an engineer, a pipeline or an AI agent, is checked against its approved change plan (FDA PCCP, EU AI Act Art. 43(4))." \
      org.opencontainers.image.source="https://github.com/a7med7emedan/medagentrx" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.authors="Ahmed Hemedan"
COPY --from=build /opt/medagentrx /opt/medagentrx
ENV PATH=/opt/medagentrx/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /work
USER 10001:10001
ENTRYPOINT ["medagentrx"]
CMD ["demo", "--out", "/tmp/medagentrx-demo"]
