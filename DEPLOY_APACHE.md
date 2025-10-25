# CloudinatorFTP Flask Production Deployment Guide

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Folder Structure](#folder-structure)
4. [Production WSGI File](#production-wsgi-file)
5. [Apache Configuration](#apache-configuration)
6. [Running the App](#running-the-app)
7. [Differences Between Dev and Production](#differences-between-dev-and-production)
8. [Troubleshooting](#troubleshooting)
9. [Best Practices](#best-practices)

---

## Overview

This guide explains how to deploy **CloudinatorFTP** (Flask app) on **Windows** using **XAMPP Apache** with **mod_wsgi**.

Key components:

| Component | Purpose |
|-----------|---------|
| Flask | Python web application |
| Apache (XAMPP) | HTTP server handling requests |
| mod_wsgi | Bridge connecting Apache to Flask |
| `.wsgi` | Entry point exposing Flask app to Apache |

---

## Prerequisites

1. **XAMPP** installed (includes Apache + MySQL).  
2. **Python 3.10+** installed.  
3. **Flask installed** in a virtual environment:

\`\`\`bash
python -m venv venv
venv\Scripts\activate
pip install flask
\`\`\`

4. **mod_wsgi** for your Apache + Python version:  
   - Download: [https://www.lfd.uci.edu/~gohlke/pythonlibs/#mod_wsgi](https://www.lfd.uci.edu/~gohlke/pythonlibs/#mod_wsgi)  
   - Copy `mod_wsgi.so` into `C:\xampp\apache\modules\`.

---

## Folder Structure

\`\`\`
C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP\
│
├── app.py               # Flask app (unchanged)
├── dev_server.py        # Development server (unchanged)
├── myflaskapp.wsgi      # Production WSGI entry point
├── venv\                # Python virtual environment
└── .python-egg-cache\   # Optional, required by mod_wsgi
\`\`\`

---

## Production WSGI File (`myflaskapp.wsgi`)

Create `myflaskapp.wsgi` in the same folder as `app.py`:

\`\`\`python
import sys
import os
from datetime import timedelta

# 1. Absolute path to project directory
sys.path.insert(0, r'C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP')

# 2. Environment variables for production
os.environ['FLASK_ENV'] = 'production'
os.environ['PYTHON_EGG_CACHE'] = r'C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP\.python-egg-cache'

# 3. Import Flask app
from app import app as application

# 4. Optional production-safe configuration
application.config.update(
    MAX_CONTENT_LENGTH=None,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    SEND_FILE_MAX_AGE_DEFAULT=0,
    TESTING=False,
    DEBUG=False,
    THREADED=True,
    PROPAGATE_EXCEPTIONS=True,
    TEMPLATES_AUTO_RELOAD=False
)
\`\`\`

**Notes:**

- Absolute paths are required for `sys.path.insert`.  
- `application` variable is required by Apache.  
- Dev features (debug, reloader) are disabled.

---

## Apache Configuration (XAMPP)

Add the following to `httpd-vhosts.conf` or `httpd.conf`:

\`\`\`apache
<VirtualHost *:80>
    ServerName localhost

    WSGIScriptAlias / "C:/Users/kyle.capistrano/Desktop/My Projects/CloudinatorFTP/myflaskapp.wsgi"

    <Directory "C:/Users/kyle.capistrano/Desktop/My Projects/CloudinatorFTP">
        Require all granted
    </Directory>

    # Optional logs
    ErrorLog "C:/xampp/apache/logs/cloudinatorftp_error.log"
    CustomLog "C:/xampp/apache/logs/cloudinatorftp_access.log" combined

    # Optional: daemon process using virtual environment
    WSGIDaemonProcess cloudinatorftp python-home="C:/Users/kyle.capistrano/Desktop/My Projects/CloudinatorFTP/venv" python-path="C:/Users/kyle.capistrano/Desktop/My Projects/CloudinatorFTP"
</VirtualHost>
\`\`\`

---

## Running the App

1. Activate virtual environment:

\`\`\`bash
cd "C:\Users\kyle.capistrano\Desktop\My Projects\CloudinatorFTP"
venv\Scripts\activate
\`\`\`

2. Restart Apache from the XAMPP Control Panel.  
3. Visit [http://localhost/](http://localhost/) → Your Flask app should appear.

---

## Differences Between Dev and Production

| Feature | Dev (`dev_server.py`) | Prod (Apache + mod_wsgi) |
|---------|----------------------|-------------------------|
| Server | Flask dev server | Apache HTTP server |
| Debug | True | False |
| Auto-reload | Enabled | No |
| Threading | Flask handles | Apache handles |
| Port | 5000 | 80 |
| Logging | Console | Apache logs |
| Environment | `FLASK_ENV=development` | `FLASK_ENV=production` |

---

## Troubleshooting

| Issue | Solution |
|-------|---------|
| 500 Internal Server Error | Check Apache error log |
| ImportError | Verify `sys.path.insert(0, <absolute_path>)` in `.wsgi` |
| Flask not loading | Ensure `application` variable exists in `.wsgi` |
| mod_wsgi fails | Check `.so` matches Apache + Python version |

---

## Best Practices

- Keep `app.py` and `dev_server.py` unchanged.  
- `.wsgi` is only for production.  
- Always use **absolute paths** in `.wsgi`.  
- Use Apache logs for production debugging.  
- Avoid enabling `DEBUG` in production.  
- Set environment variables for secrets/config in `.wsgi` or Apache.  

---

**End of Guide**
