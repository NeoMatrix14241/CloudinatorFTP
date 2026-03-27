# CloudinatorFTP Apache/mod_wsgi Production Deployment Guide

A complete guide to deploy CloudinatorFTP in production using Apache HTTP Server with mod_wsgi on Windows (XAMPP).

## 📋 Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [System Requirements](#system-requirements)
4. [Installation Steps](#installation-steps)
5. [Production WSGI File](#production-wsgi-file)
6. [Apache Configuration](#apache-configuration)
7. [Enabling mod_wsgi in Apache](#enabling-modwsgi-in-apache)
8. [Deployment Verification](#deployment-verification)
9. [Differences: Dev vs Production](#differences-dev-vs-production)
10. [Troubleshooting](#troubleshooting)
11. [Best Practices](#best-practices)

---

## Overview

This guide explains how to deploy **CloudinatorFTP** (Flask app) in production on **Windows** using **XAMPP Apache** with **mod_wsgi**.

### Architecture

```
User Request 
    ↓
Apache HTTP Server (Port 80)
    ↓
mod_wsgi Module
    ↓
Python Virtual Environment
    ↓
Flask Application (CloudinatorFTP)
    ↓
SQLite Database + File Storage
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **Apache (XAMPP)** | HTTP server handling requests |
| **mod_wsgi** | Bridge connecting Apache to Python/Flask |
| **Virtual Environment** | Isolated Python environment with dependencies |
| **WSGI File** | Entry point exposing Flask to Apache |
| **Flask App** | CloudinatorFTP application |

---

## Prerequisites

- ✅ **XAMPP** installed with Apache (version 2.4+)
- ✅ **Python 3.10+** installed and added to PATH
- ✅ **Administrator access** on Windows
- ✅ **Internet connection** for downloads
- ✅ **Basic Apache knowledge** (editing config files)

### Tested Configuration

- ✅ XAMPP 3.3.0+ with Apache 2.4.54+
- ✅ Python 3.10, 3.11, 3.12
- ✅ Windows 10, Windows 11, Windows Server 2019+

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **RAM** | 1 GB | 4 GB |
| **CPU** | 2 Cores | 4+ Cores |
| **Storage** | 1 GB | 20+ GB |
| **Apache** | 2.4.0+ | 2.4.54+ |
| **Python** | 3.10 | 3.11, 3.12 |

---

## Installation Steps

### Step 1: Verify Python Installation

Open Command Prompt and verify Python is installed and in PATH:

```cmd
python --version
pip --version
```

Expected output:
```
Python 3.11.x
pip 24.x.x from C:\Users\...\AppData\Local\Programs\Python\Python311\lib\site-packages\pip
```

If not found: Add Python to PATH via `sysdm.cpl` → Environment Variables

### Step 2: Create Virtual Environment

```cmd
cd C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP
python -m venv venv
venv\Scripts\activate.bat
```

You should see `(venv)` in your command prompt.

### Step 3: Install CloudinatorFTP Dependencies

```cmd
pip install -r requirements.txt
pip cache purge
```

### Step 4: Install mod_wsgi

```cmd
pip install mod_wsgi
```

✅ **Success Message**: You should see `Successfully installed mod-wsgi-x.x.x`

---

## Production WSGI File

### Step 5: Create `myflaskapp.wsgi`

Create a new file `myflaskapp.wsgi` in the project root directory.

**File Location**: `C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP\myflaskapp.wsgi`

**Content**:

```python
#!/usr/bin/env python3
"""
myflaskapp.wsgi — Production WSGI entry point for CloudinatorFTP
Used by Apache + mod_wsgi to run the Flask application
"""

import sys
import os
from datetime import timedelta

# 1. Absolute path to project directory (REQUIRED for Apache)
sys.path.insert(0, r'C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP')

# 2. Set environment variables for production
os.environ['FLASK_ENV'] = 'production'
os.environ['PYTHONUNBUFFERED'] = '1'

# 3. Python egg cache (required for mod_wsgi with packages)
os.environ['PYTHON_EGG_CACHE'] = r'C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP\.python-egg-cache'

egg_cache = os.environ['PYTHON_EGG_CACHE']
if not os.path.exists(egg_cache):
    try:
        os.makedirs(egg_cache)
    except OSError:
        pass

# 4. Import and configure Flask application
from app import app as application

# 5. Production-safe configuration
application.config.update(
    DEBUG=False,
    TESTING=False,
    MAX_CONTENT_LENGTH=None,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    SEND_FILE_MAX_AGE_DEFAULT=0,
    THREADED=True,
    PROPAGATE_EXCEPTIONS=True,
    TEMPLATES_AUTO_RELOAD=False,
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)
```

---

## Apache Configuration

### Step 6: Get mod_wsgi Configuration

In Command Prompt (with venv activated), run:

```cmd
venv\Scripts\activate.bat
mod_wsgi-express module-config
```

Example output:
```
LoadModule wsgi_module "c:/users/kyle.capistrano/desktop/my projects/cloudinatorftp/venv/Lib/site-packages/mod_wsgi/server/mod_wsgi.so"
WSGIPythonHome "c:/users/kyle.capistrano/desktop/my projects/cloudinatorftp/venv"
```

**Copy this output** — you'll need it for Apache configuration.

### Step 7: Enable Virtual Hosts in Apache

1. Navigate to: `C:\xampp\apache\conf\httpd.conf`
2. Find the line: `#Include conf/extra/httpd-vhosts.conf`
3. Remove the `#` to uncomment:
   ```
   Include conf/extra/httpd-vhosts.conf
   ```
4. Save the file

### Step 8: Configure Virtual Host

Edit: `C:\xampp\apache\conf\extra\httpd-vhosts.conf`

**Add this configuration** at the end of the file:

```apache
# CloudinatorFTP Production Deployment
<VirtualHost *:80>
    ServerName localhost
    ServerAlias 127.0.0.1
    DocumentRoot "C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP"

    # 1. Paste the mod_wsgi module config here (from Step 6)
    LoadModule wsgi_module "c:/users/kyle.capistrano/desktop/my projects/cloudinatorftp/venv/Lib/site-packages/mod_wsgi/server/mod_wsgi.so"
    WSGIPythonHome "c:/users/kyle.capistrano/desktop/my projects/cloudinatorftp/venv"

    # 2. WSGI Script Alias (maps / to your WSGI app)
    WSGIScriptAlias / "C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP\myflaskapp.wsgi"

    # 3. Directory permissions
    <Directory "C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP">
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    # 4. Daemon process configuration (recommended)
    WSGIDaemonProcess cloudinatorftp python-home="C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP\venv" python-path="C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP" processes=1 threads=15 maximum-requests=1000 socket-timeout=600

    # 5. Route requests through daemon process
    WSGIProcessGroup cloudinatorftp

    # 6. Logging (optional but recommended)
    ErrorLog "C:/xampp/apache/logs/cloudinatorftp_error.log"
    CustomLog "C:/xampp/apache/logs/cloudinatorftp_access.log" combined
    LogLevel warn

    # 7. File uploads
    LimitRequestBody 17179869184
</VirtualHost>
```

**⚠️ Important**: Update the paths to match your actual installation directory!

---

## Enabling mod_wsgi in Apache

### Step 9: Verify Apache Configuration

```cmd
cd C:\xampp\apache\bin
httpd -t
```

Expected output: `Syntax OK`

❌ **If error**: Check the error message and fix the config file.

### Step 10: Restart Apache

**Using XAMPP Control Panel**:
1. Click "Stop" for Apache
2. Wait for it to fully stop
3. Click "Start" for Apache
4. Check that it shows **green** "Started"

**Or via Command Prompt (Admin)**:
```cmd
cd C:\xampp\apache\bin
apache -k graceful
```

### Step 11: Test the Deployment

Open your browser and visit:
```
http://localhost/
```

✅ **Success**: CloudinatorFTP login page should appear

---

## Deployment Verification

### Verify App is Running

Check the Apache error log:

```cmd
type C:\xampp\apache\logs\cloudinatorftp_error.log | findstr CloudinatorFTP
```

### Monitor Access Logs

```cmd
tail -f C:\xampp\apache\logs\cloudinatorftp_access.log
```

---

## Differences: Dev vs Production

| Feature | Dev (`dev_server.py`) | Production (Apache + mod_wsgi) |
|---------|----------------------|--------------------------------|
| **Server** | Flask Development Server | Apache HTTP Server |
| **Debug Mode** | True | False |
| **Auto-reload** | Enabled | Disabled |
| **Threading** | Flask handles | Apache handles |
| **Port** | 5000 | 80 |
| **Logging** | Console | Apache log files |
| **Environment** | `FLASK_ENV=development` | `FLASK_ENV=production` |
| **Performance** | Lower (not optimized) | Higher (optimized) |
| **Concurrency** | Single process | Multiple processes |
| **Error Display** | Full stack traces | User-friendly pages |

---

## Troubleshooting

### Error: "ModuleNotFoundError: No module named 'app'"

**Cause**: `sys.path.insert(0, ...)` path is wrong

**Solution**:
1. Verify absolute path in `myflaskapp.wsgi`
2. Use raw strings: `r'C:\path\to\project'`
3. Restart Apache

### Error: "500 Internal Server Error"

**Check the error log**:
```cmd
type C:\xampp\apache\logs\cloudinatorftp_error.log
```

**Fix**:
```cmd
venv\Scripts\activate.bat
pip install -r requirements.txt
```

### Error: "403 Forbidden"

**Right-click project folder → Properties → Security**:
- Select "Users" → Check "Modify"
- Click Apply
- Restart Apache

### Error: "mod_wsgi not found"

**Solution**:
```cmd
pip uninstall mod-wsgi
pip install mod-wsgi
mod_wsgi-express module-config
```

### App loads but shows old version

**Fix**:
```cmd
rmdir /s /q __pycache__
cd C:\xampp\apache\bin
httpd -k graceful
```

### File Upload Fails

**Check `myflaskapp.wsgi`**:
```
MAX_CONTENT_LENGTH=None
```

---

## Best Practices

### Security
- ✅ Always set `DEBUG=False` in production
- ✅ Use HTTPS with SSL certificates
- ✅ Keep database outside web root
- ✅ Regularly update Apache and Python
- ✅ Change default user credentials immediately

### Performance
- ✅ Use 1-2 daemon processes
- ✅ Set thread count to 10-20
- ✅ Monitor Apache error logs
- ✅ Enable compression in Apache
- ✅ Set cache headers for static content

### Maintenance
- ✅ Keep dependencies updated
- ✅ Test updates in dev first
- ✅ Backup database regularly
- ✅ Monitor disk space
- ✅ Set up log rotation

---

## Next Steps

1. ✅ Deployment complete
2. 🔐 Change default user credentials
3. 📊 Set up log monitoring
4. 🔄 Configure regular backups
5. 📈 Monitor performance

---

## Additional Resources

- [Apache Documentation](https://httpd.apache.org/docs/)
- [mod_wsgi Documentation](https://modwsgi.readthedocs.io/)
- [Flask Production Deployment](https://flask.palletsprojects.com/en/latest/deploying/)
- [XAMPP Documentation](https://www.apachefriends.org/)
- [Windows Deployment Guide](./WINDOWS_DEPLOYMENT.md)

---

**Last Updated**: March 2026  
**Status**: Production Ready ✅
