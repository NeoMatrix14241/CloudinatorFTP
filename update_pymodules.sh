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
)

for pkg in "${packages[@]}"; do
    latest=$(pip index versions "$pkg" 2>/dev/null | grep -oP "(?<=Available versions: )[\d.]+")

    if [ -n "$latest" ]; then
        echo "Updating $pkg==$latest"
        sed -i -E "s/^${pkg}==.*/${pkg}==${latest}/" "$REQ"
    else
        echo "[WARN] Could not fetch version for $pkg, skipping..."
    fi
done

echo "Done. Updated $REQ module versions to latest available on PyPI."

read -p "Do you want to install/update these packages now? (y/n): " choice

case "$choice" in
    y|Y )
        echo "Installing updated packages..."
        python -m pip install -r "$REQ" --upgrade
        read -p "Press any key to exit..."
        ;;
    * )
        echo "Skipped installation. You can run:"
        echo "pip install -r $REQ --upgrade"
        read -p "Press any key to exit..."
        ;;
esac
