FROM python:alpine

ENV SHELL=/bin/sh \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0 \
    CC=/usr/bin/clang \
    CXX=/usr/bin/clang++

COPY requirements.txt /srv
WORKDIR /srv

RUN \
# Create user
    addgroup -g 423 -S kernelcollector \
    && adduser -u 423 -S kernelcollector -G kernelcollector \
# Upgrade system
    && apk update \
    && apk add --no-cache --virtual .dev-deps g++ clang autoconf automake make wget bzip2-dev linux-headers perl zlib-dev zstd-dev file patch grep \
    && apk add --no-cache gnupg gzip fakeroot xz tar zlib bzip2 zstd-libs \
# Compile dpkg from source (needed for zstd support)
    && cd /tmp \
# Find latest version of dpkg
    && DPKG_URL="http://archive.ubuntu.com/ubuntu/pool/main/d/dpkg" \
    && DPKG_VERSION=$(wget -q -O - "$DPKG_URL/?C=M;O=D" | grep -Poh -m 1 "(?<=\")dpkg_.+\.tar\.xz(?=\")") \
    && wget "$DPKG_URL/$DPKG_VERSION" \
    && tar -xf *.tar.xz \
    && rm -rf *.tar.xz \
    && cd dpkg-* \
    && ./configure --prefix=/usr \
         --sysconfdir=/etc \
         --mandir=/tmp \
         --localstatedir=/tmp \
         --with-libz \
         --with-libbz2 \
         --with-libzstd \
         --disable-dselect \
         --disable-start-stop-daemon \
         --disable-nls \
         --disable-static \
    && make -j$(nproc) \
    && make install \
    && cd /srv \
# Install Python dependencies
    && pip install --no-cache --upgrade -r requirements.txt \
    && chown -R kernelcollector:kernelcollector . \
# Cleanup
    && apk del .dev-deps \
    && rm -rf /tmp/* /var/cache/apk/*

COPY . /srv

USER kernelcollector
ENTRYPOINT ["/bin/sh", "/srv/entrypoint.sh"]
