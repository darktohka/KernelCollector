#!/bin/sh

# Import our GPG key
gpg --import gpg.key

# Run the actual program
python -m kernelcollector.Main
