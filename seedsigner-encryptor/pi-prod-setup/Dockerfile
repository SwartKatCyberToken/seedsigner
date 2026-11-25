# The seedsigner-os builder plus qemu-user-static, so build-in-container.sh
# can run the image's own ARM python3 to test the message crypto imports.
FROM seedsigner-os-builder

RUN apt-get -qq update \
    && apt-get -y install qemu-user-static \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
ENTRYPOINT ["/bin/bash"]
