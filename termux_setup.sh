#!/bin/bash

# ==============================================================================
# CONFIGURATION
# ==============================================================================
MAX_RETRIES=5
RETRY_COUNT=0
SUCCESS=false

# Define the main setup sequence as a function
run_setup() {
    echo "==> Step 1: Updating system and installing pkg dependencies..."
    pkg --check-mirror update && \
    pkg update -y && \
    pkg upgrade -y && \
    pkg install -y build-essential clang make binutils llvm rust python \
                   python-pip python-bcrypt python-cryptography python-psutil \
                   libffi openssl libxml2 libxslt git cloudflared ffmpeg libvips || return 1

    echo "==> Step 2: Upgrading pip and core tools..."
    pip install --upgrade pip setuptools wheel || return 1
    pip cache purge || return 1

    echo "==> Step 3: Downloading and patching pyppmd..."
    pip uninstall pyppmd -y || true 
    
    mkdir -p "$TMPDIR/ppmd"
    cd "$TMPDIR/ppmd" || return 1
    
    # Fixed the missing && here
    rm -rf pyppmd-1.3.1* && \
    pip download pyppmd==1.3.1 --no-binary pyppmd -d "$TMPDIR/ppmd" || return 1
    
    tar -xzf pyppmd-1.3.1.tar.gz || return 1
    cd pyppmd-1.3.1 || return 1
    
    # Patch the C source file
    sed -i 's/pthread_cancel(tc->handle);/pthread_kill(tc->handle, SIGTERM);/g' src/lib/buffer/ThreadDecoder.c || return 1
    
    # Patch the pyproject.toml
    python3 << 'EOF' || return 1
import re
with open('pyproject.toml', 'r') as f:
    c = f.read()
c = c.replace('dynamic = ["version"]', 'version = "1.3.1"')
c = re.sub(r'\[tool\.setuptools_scm\].*?(?=\[|\Z)', '', c, flags=re.DOTALL)
c = re.sub(r',?\s*"setuptools.scm[^"]*"', '', c)
with open('pyproject.toml', 'w') as f:
    f.write(c)
EOF

    # Install the patched pyppmd
    pip install . --no-build-isolation --no-cache-dir || return 1

    echo "==> Step 4: Installing remaining Python packages..."
    pip install py7zr --no-deps || return 1
    pip install PyCryptodomex pybcj texttable multivolumefile brotli backports.zstd inflate64 || return 1

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
        SUCCESS=true
        break
    else
        echo -e "\n[ERROR] Setup failed on attempt $((RETRY_COUNT + 1))."
        RETRY_COUNT=$((RETRY_COUNT + 1))
        
        # CHANGED 'do' TO 'then' HERE
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