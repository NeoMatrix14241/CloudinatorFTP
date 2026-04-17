#!/bin/bash

# Note: Re-run again if error(s) are encountered as this includes two patches for PyPPMd (a py7zr dependency) to build on Android:
#   1. pthread_cancel() → pthread_kill(SIGTERM) workaround (Android's bionic libc lacks pthread_cancel)
#   2. pyproject.toml version patched to 1.3.1 (setuptools_scm can't detect version from tarball, defaults to 0.0.0)
# pkg --check-mirror update && pkg update -y && pkg upgrade -y && pkg install -y build-essential clang make binutils llvm rust python python-pip python-bcrypt python-cryptography python-psutil libffi openssl libxml2 libxslt git cloudflared ffmpeg libvips && pip install --upgrade pip setuptools wheel && pip cache purge && pip uninstall pyppmd -y ; pip download pyppmd==1.3.1 --no-binary pyppmd -d $TMPDIR/ppmd && cd $TMPDIR/ppmd && rm -rf pyppmd-1.3.1 && tar -xzf pyppmd-1.3.1.tar.gz && cd pyppmd-1.3.1 && sed -i 's/pthread_cancel(tc->handle);/pthread_kill(tc->handle, SIGTERM);/g' src/lib/buffer/ThreadDecoder.c && python3 -c "
# import re
# c = open('pyproject.toml').read()
# c = c.replace('dynamic = [\"version\"]', 'version = \"1.3.1\"')
# c = re.sub(r'\[tool\.setuptools_scm\].*?(?=\[|\Z)', '', c, flags=re.DOTALL)
# c = re.sub(r',?\s*\"setuptools.scm[^\"]*\"', '', c)
# open('pyproject.toml','w').write(c)
# " && pip install . --no-build-isolation --no-cache-dir && pip install py7zr --no-deps && pip install PyCryptodomex pybcj texttable multivolumefile brotli backports.zstd inflate64
# && cd ~

# ==============================================================================
# CONFIGURATION
# ==============================================================================

MAX_RETRIES=5
RETRY_COUNT=0
SUCCESS=false

# Define the main setup sequence as a function
run_setup() {
    echo "==> Updating system and installing pkg dependencies..."
    pkg --check-mirror update && \
    pkg update -y && \
    pkg upgrade -y && \
    pkg install -y build-essential clang make binutils llvm rust python \
    python-pip python-bcrypt python-cryptography python-pyppmd python-psutil \
    libffi openssl libxml2 libxslt git cloudflared ffmpeg libvips || return 1
    return 0
}

# ==============================================================================
# EXECUTION LOOP
# ==============================================================================

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    echo "============================================================"
    echo " Starting Setup - Attempt $((RETRY_COUNT + 1)) of $MAX_RETRIES "
    echo "============================================================"

    if run_setup; then
        echo -e "\n[SUCCESS] Termux setup completed successfully!"

        echo "==> Requesting storage access..."
        termux-setup-storage
        echo "[INFO] Waiting for you to accept the permission dialog..."

        while true; do
            if [ -d ~/storage ]; then
                echo "[OK] Storage access granted!"
                break
            fi
            sleep 1
        done

        SUCCESS=true
        break
    else
        echo -e "\n[ERROR] Setup failed on attempt $((RETRY_COUNT + 1))."
        RETRY_COUNT=$((RETRY_COUNT + 1))

        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            echo "Retrying in 5 seconds..."
            sleep 5
        fi
    fi
done

if [ "$SUCCESS" = false ]; then
    echo -e "\n[CRITICAL] Setup failed after $MAX_RETRIES attempts."
    exit 1
fi