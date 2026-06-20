#!/bin/bash

REQ="requirements.txt"

packages=(
    Flask
    flask-cors
    bcrypt
    zipstream-new
    Werkzeug
    watchdog
    waitress
    cryptography
    mammoth
    openpyxl
    python-pptx
    rarfile
    pyzipper
    py7zr
    pyvips
    wsgidav
    paramiko
    pyftpdlib
    cheroot
)

# Ensure the requirements file exists
touch "$REQ"

for pkg in "${packages[@]}"; do
    # Fetch the single latest version string
    latest=$(pip index versions "$pkg" 2>/dev/null | grep -oP "(?<=Available versions: )[\d.]+" | head -n 1)
    
    if [ -n "$latest" ]; then
        # CRITICAL FIX: Handle the known bcrypt/wsgidav dependency wall
        if [ "$pkg" == "bcrypt" ]; then
            echo "[FIX] Enforcing wsgidav compatibility for bcrypt..."
            constraint=">=4.0,<5.0"
        else
            # Extract the major version number (e.g., "4.3.4" -> "4")
            major_version=$(echo "$latest" | cut -d. -f1)
            next_major=$((major_version + 1))
            constraint=">=${latest},<${next_major}"
        fi
        
        echo "Updating $pkg to $constraint"
        
        # Check if the package already exists in requirements.txt
        if grep -qE "^${pkg}([>=<~!]|$)" "$REQ"; then
            # Replace the existing line regardless of whether it used ==, >=, etc.
            sed -i -E "s/^${pkg}([>=<~!].*)?/${pkg}${constraint}/" "$REQ"
        else
            # Append if it doesn't exist
            echo "${pkg}${constraint}" >> "$REQ"
        fi
    else
        echo "[WARN] Could not fetch version for $pkg, skipping..."
    fi
done

echo "Done. Updated $REQ module constraints to compatible ranges."

read -p "Do you want to install/update these packages now? (y/n): " choice

case "$choice" in
    y|Y )
        echo "Installing updated packages..."
        python -m pip install -r "$REQ" --upgrade --no-cache-dir
        read -p "Press any key to exit..."
    ;;
    * )
        echo "Skipped installation. You can run:"
        echo "pip install -r $REQ --upgrade --no-cache-dir"
        read -p "Press any key to exit..."
    ;;
esac