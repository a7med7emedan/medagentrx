# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
#
# MedAgentRx container. Runs as UID 10001, works with --read-only and a
# tmpfs on /tmp, and needs no shell at run time.
#   docker build -t medagentrx .
#   docker run --rm --read-only --tmpfs /tmp medagentrx

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.15@sha256:62f8c047d0a0e9ece6b53fc63df902585a67a47a7f318ddec4a37db586edc8e3 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/medagentrx
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv sync --frozen --no-dev --extra web --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra web --no-editable
# Remove what MedAgentRx never loads: test suites, C headers and sources, and
# pyarrow's remote file systems and Flight. pyarrow imports these
# only on demand, so local Parquet reading and writing are unaffected.
WORKDIR /opt/medagentrx/lib/python3.12/site-packages
RUN find . -depth -type d \( -name tests -o -name __pycache__ \) -exec rm -rf {} + \
 && rm -rf pyarrow/include pyarrow/src pyarrow/*.pyx pyarrow/*.pxd pyarrow/includes \
           numpy/f2py numpy/_pyinstaller matplotlib/mpl-data/sample_data \
 && rm -f pyarrow/libarrow_flight.so* pyarrow/libarrow_python_flight.so* pyarrow/_flight.*.so \
          pyarrow/libarrow_s3.so* pyarrow/_s3fs.*.so \
          pyarrow/_gcsfs.*.so pyarrow/_azurefs.*.so pyarrow/_hdfs.*.so

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ARG VERSION=0.2.0
LABEL org.opencontainers.image.title="MedAgentRx" \
      org.opencontainers.image.description="Every model update, by an engineer, a pipeline or an AI agent, is checked against its approved change plan (FDA PCCP, EU AI Act Art. 43(4))." \
      org.opencontainers.image.source="https://github.com/a7med7emedan/medagentrx" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.authors="Ahmed Hemedan"
COPY --from=build /opt/medagentrx /opt/medagentrx
# Purge base packages the tool never uses, several with open HIGH findings
# and no fix yet: util-linux and mount tools, ncurses, bash, perl, apt,
# systemd libraries and ACL support. /bin/sh (dash) stays for CI job
# scripts; cp and mv no longer work because they need libacl.
# hadolint ignore=DL3059
RUN rm -rf /var/lib/apt /var/cache/apt /var/log/* /usr/share/doc /usr/share/man \
           /usr/local/lib/python3.12/site-packages/pip* /usr/local/bin/pip* \
 && dpkg --purge --no-triggers --force-remove-essential --force-remove-protected --force-depends \
      bash bsdutils login mount util-linux libmount1 libblkid1 libsmartcols1 liblastlog2-2 \
      libuuid1 ncurses-base ncurses-bin libncursesw6 libtinfo6 perl-base \
      libsystemd0 libudev1 libacl1 apt libapt-pkg7.0 \
 && ldconfig
ENV PATH=/opt/medagentrx/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /work
USER 10001:10001
ENTRYPOINT ["medagentrx"]
CMD ["demo", "--out", "/tmp/medagentrx-demo"]
