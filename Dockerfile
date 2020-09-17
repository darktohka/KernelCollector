FROM python:rc-alpine

ENV SHELL /bin/sh
ENV LANG C.UTF-8

ENV PYTHONUNBUFFERED 1
ENV PIP_DISABLE_PIP_VERSION_CHECK 1
ENV PIP_NO_CACHE_DIR 0

COPY . /srv
WORKDIR /srv

RUN \
# Create user
    addgroup -g 423 -S kernelcollector \
    && adduser -u 423 -S kernelcollector -G kernelcollector \
# Upgrade system
    && apk update \
    && apk upgrade --no-cache \
    && apk add --no-cache dpkg gnupg gzip fakeroot xz tar \
# Install Python dependencies
    && pip install --no-cache --upgrade -r requirements.txt \
    && chown -R kernelcollector:kernelcollector . \
# Cleanup
    && rm -rf /tmp/* /var/cache/apk/*

USER kernelcollector
ENTRYPOINT ["/bin/sh", "/srv/entrypoint.sh"]
