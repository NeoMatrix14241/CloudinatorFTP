# CloudinatorFTP Production Deployment Guide

## WSGI Deployment Options

### Option 1: Gunicorn (Linux/macOS)
```bash
# Install dependencies
pip install -r requirements.txt

# Run with Gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 wsgi:application

# With additional options
gunicorn --bind 0.0.0.0:5000 \
         --workers 4 \
         --worker-class sync \
         --timeout 120 \
         --max-requests 1000 \
         --max-requests-jitter 100 \
         --preload \
         --access-logfile - \
         --error-logfile - \
         wsgi:application
```

### Option 2: Waitress (Cross-platform, Windows compatible)
```bash
# Install dependencies
pip install -r requirements.txt

# Run with Waitress
waitress-serve --host=0.0.0.0 --port=5000 wsgi:application

# With additional options
waitress-serve --host=0.0.0.0 --port=5000 --threads=8 --channel-timeout=120 wsgi:application
```

### Option 3: uWSGI (Linux/macOS)
```bash
# Install uWSGI
pip install uwsgi

# Run with uWSGI
uwsgi --http 0.0.0.0:5000 --module wsgi:application --processes 4 --threads 2
```

## Configuration Files

### Gunicorn Configuration (gunicorn.conf.py)
```python
# gunicorn.conf.py
bind = "0.0.0.0:5000"
workers = 4
worker_class = "sync"
timeout = 120
max_requests = 1000
max_requests_jitter = 100
preload_app = True
access_logfile = "-"
error_logfile = "-"
```

### Systemd Service (Linux)
```ini
# /etc/systemd/system/cloudinatorftp.service
[Unit]
Description=CloudinatorFTP WSGI Server
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/path/to/CloudinatorFTP
Environment=PATH=/path/to/venv/bin
ExecStart=/path/to/venv/bin/gunicorn --config gunicorn.conf.py wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

## Reverse Proxy Setup

### Nginx Configuration
```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 10G;  # For large file uploads

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # For chunked uploads
        proxy_request_buffering off;
        proxy_buffering off;
        
        # Timeout settings
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    # Static files (optional optimization)
    location /static {
        alias /path/to/CloudinatorFTP/static;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }
}
```

### Apache Configuration
```apache
<VirtualHost *:80>
    ServerName your-domain.com
    DocumentRoot /path/to/CloudinatorFTP
    
    ProxyPreserveHost On
    ProxyPass /static !
    ProxyPass / http://127.0.0.1:5000/
    ProxyPassReverse / http://127.0.0.1:5000/
    
    # Static files
    Alias /static /path/to/CloudinatorFTP/static
    <Directory "/path/to/CloudinatorFTP/static">
        Require all granted
    </Directory>
</VirtualHost>
```

## Docker Deployment

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create storage directory
RUN mkdir -p storage

# Expose port
EXPOSE 5000

# Run with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "wsgi:application"]
```

### Docker Compose
```yaml
version: '3.8'

services:
  cloudinatorftp:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./storage:/app/storage
      - ./users.json:/app/users.json
      - ./storage_config.json:/app/storage_config.json
    environment:
      - FLASK_ENV=production
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
    depends_on:
      - cloudinatorftp
    restart: unless-stopped
```

## Environment Variables

Set these environment variables for production:
```bash
export FLASK_ENV=production
export FLASK_DEBUG=False
export SECRET_KEY=your-secret-key-here
```

## Performance Tuning

1. **Worker Processes**: Use `(2 × CPU cores) + 1` workers
2. **Memory**: Monitor memory usage and adjust workers accordingly
3. **Timeouts**: Increase for large file uploads (120+ seconds)
4. **Static Files**: Serve via reverse proxy for better performance
5. **Database**: Consider SQLite WAL mode or PostgreSQL for high concurrency

## Security Considerations

1. **Reverse Proxy**: Always use Nginx/Apache in production
2. **HTTPS**: Enable SSL/TLS certificates
3. **Firewall**: Restrict direct access to WSGI server
4. **File Permissions**: Proper user/group permissions
5. **Upload Limits**: Configure appropriate file size limits
