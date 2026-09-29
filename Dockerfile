# The full Debian-based image rather than -slim: swh.web's dependency tree
# loads libpq (psycopg, via swh.indexer) and libmagic (python-magic, via
# swh.web.browse) at import time, and both ship here.
FROM python:3.11

ARG SWH_WEB_VERSION=0.17.12

RUN pip install --no-cache-dir "swh.web==${SWH_WEB_VERSION}"

COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-dev.txt

WORKDIR /gen
