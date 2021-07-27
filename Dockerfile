FROM python:alpine

ENV SHELL /bin/sh
ENV LANG C.UTF-8

ENV PYTHONUNBUFFERED 1
ENV PIP_DISABLE_PIP_VERSION_CHECK 1
ENV PIP_NO_CACHE_DIR 0
ENV CC /usr/bin/clang
ENV CXX /usr/bin/clang++

COPY requirements.txt /srv
WORKDIR /srv

RUN \
# Create user
    addgroup -g 423 -S kernelcollector \
    && adduser -u 423 -S kernelcollector -G kernelcollector \
# Upgrade system
    && apk update \
    && apk add --no-cache --virtual .dev-deps g++ clang autoconf automake make wget bzip2-dev linux-headers perl zlib-dev zstd-dev file patch \
    && apk add --no-cache gnupg gzip fakeroot xz tar zlib bzip2 zstd-libs \
# Compile dpkg from source (needed for zstd support)
    && cd /tmp \
    && wget https://launchpad.net/ubuntu/+archive/primary/+sourcefiles/dpkg/1.20.9ubuntu2/dpkg_1.20.9ubuntu2.tar.xz \
    && tar -xvf *.tar.xz \
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
