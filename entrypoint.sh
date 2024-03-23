#!/bin/sh
set -e

# Import our GPG key
gpg --import gpg.key

# Run the actual program
python -m kernelcollector.main

# Ping the URL if it is set
if [[ -n "$PING_URL" ]]; then
    curl -m 10 --retry 5 "$PING_URL"
fi