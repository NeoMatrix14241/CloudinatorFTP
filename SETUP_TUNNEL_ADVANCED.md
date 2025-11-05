# Cloudflare Tunnel Setup Documentation

A complete guide to expose your local service (localhost:5000) to the internet using Cloudflare Tunnel.

## Overview
This documentation covers the end-to-end process of setting up a Cloudflare Tunnel to securely expose your local application to the internet through your domain.

**Architecture Flow:**
```
[Your App on localhost:5000] → [Cloudflared Tunnel] → [Cloudflare Network] → [Your Domain (domain.com)]
```

## Prerequisites
- Windows machine (for Linux/Mac, adjust paths accordingly)
- Application running on `http://localhost:5000`
- Admin access to your computer
- Cloudflare account (free tier works)
- Domain already purchased from a registrar

---

## Step 1: Domain Registration

Ensure you have already purchased a domain from any registrar:
- **Popular Registrars:** Namecheap, GoDaddy, Google Domains, Porkbun, Cloudflare Registrar
- **Note:** You don't need to buy hosting - Cloudflare Tunnel replaces traditional hosting

---

## Step 2: Onboard Domain to Cloudflare

### Detailed Steps:

1. **Navigate to Cloudflare Dashboard**
   - Go to https://dash.cloudflare.com

2. **Start Domain Onboarding**
   - Click **"+Onboard a domain"** button

3. **Enter Your Domain**
   - Enter the domain you purchased (e.g., `domain.com`)
   - Click Continue

4. **DNS Records Setup**
   - Select **"Manually enter DNS records"**
   - *Important: We'll let cloudflared tunnel handle DNS records automatically*

5. **Select Plan**
   - Choose **Free plan** (sufficient for tunnel setup)
   - Click Continue

6. **Skip DNS Records**
   - When asked to add DNS records, **do not add any**
   - The cloudflared tunnel CLI will handle this automatically
   - Click **"Continue to Activation"**

7. **Confirm Skip**
   - A modal for **"Add records later"** will appear
   - Click **"Confirm"**

8. **Nameserver Configuration Instructions**
   - Cloudflare will display on-screen instructions showing:
     - Two nameservers (e.g., `dahlia.ns.cloudflare.com`, `bruce.ns.cloudflare.com`)
     - Instructions to log in to your domain provider
     - Reminder to **disable DNSSEC** at your registrar
     - Instructions to update nameservers

9. **Complete Initial Setup**
   - Click **"Continue"**
   - Your domain is now added to Cloudflare (pending nameserver update)

---

## Step 3: Configure Domain at Your Registrar

### 3.1 Disable DNSSEC (Important!)
1. Log in to your domain registrar
2. Find DNSSEC settings (usually under DNS or Advanced settings)
3. **Disable DNSSEC** if enabled
4. Save changes

### 3.2 Update Nameservers
1. In your registrar's dashboard, find DNS/Nameserver settings
2. Change from default nameservers to Cloudflare's nameservers:
   - Remove existing nameservers
   - Add the two Cloudflare nameservers provided
3. Save changes

### 3.3 Verify Propagation
**Check nameserver status (may take 5 minutes to 48 hours):**
```cmd
nslookup -type=NS domain.com
```

**Cloudflare Dashboard Status:**
- Return to Cloudflare Dashboard
- Your domain should show **"Active"** status once propagation completes
- You'll receive an email when activation is complete

---

## Step 4: Install Cloudflared

### Windows Installation Options:

**Option A - Using Winget (Recommended):**
```powershell
winget install Cloudflare.cloudflared
```

**Option B - Using Chocolatey:**
```powershell
choco install cloudflared
```

**Option C - Manual Download:**
1. Visit: https://github.com/cloudflare/cloudflared/releases
2. Download `cloudflared-windows-amd64.exe`
3. Rename to `cloudflared.exe`
4. Add to PATH or use full path when running

### Verify Installation:
```cmd
cloudflared --version
```

---

## Step 5: Authenticate Cloudflared

Run the authentication command:
```cmd
cloudflared tunnel login
```

**What happens:**
1. Browser opens automatically
2. Log in to Cloudflare (if not already logged in)
3. Select the zone/domain you just added
4. Click "Authorize"
5. Certificate downloads to `C:\Users\%USERNAME%\.cloudflared\cert.pem`
6. Terminal shows: "You have successfully logged in."

---

## Step 6: Create the Tunnel

### 6.1 Create a New Tunnel
```cmd
cloudflared tunnel create my-app-tunnel
```

**Output example:**
```
Tunnel credentials written to C:\Users\%USERNAME%\.cloudflared\6ff42ae2-765d-4adf-8112-31c55c1551ef.json
Created tunnel my-app-tunnel with id 6ff42ae2-765d-4adf-8112-31c55c1551ef
```

**Important:** Save the tunnel ID (the UUID) - you'll need it for configuration.

### 6.2 Verify Tunnel Creation
```cmd
cloudflared tunnel list
```

---

## Step 7: Configure the Tunnel

### 7.1 Create Configuration File
Create file: `C:\Users\%USERNAME%\.cloudflared\config.yml`

**Configuration Content:**
```yaml
tunnel: <tunnel-id>
credentials-file: C:\Users\%USERNAME%\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: domain.com
    service: http://localhost:5000
    originRequest:
      connectTimeout: 0s
      tlsTimeout: 0s
      tcpKeepAlive: 0s
      keepAliveTimeout: 0s
      httpHostHeader: domain.com
      noTLSVerify: true
      disableChunkedEncoding: false
      proxyConnectTimeout: 0s
      expectContinueTimeout: 0s
  - service: http_status:404
```

**Replace:**
- `<tunnel-id>` with your actual tunnel ID from Step 6
- `%USERNAME%` with your Windows username
- `domain.com` with your actual domain

### 7.2 Configuration Parameters Explained

| Parameter | Purpose | Development | Production |
|-----------|---------|------------|------------|
| `tunnel` | Your unique tunnel identifier | Required | Required |
| `credentials-file` | Path to tunnel authentication file | Required | Required |
| `hostname` | Domain that will route to this service | Your domain | Your domain |
| `service` | Local service to expose | http://localhost:5000 | Your service URL |
| `httpHostHeader` | Host header sent to origin | domain.com | domain.com |
| `noTLSVerify` | Skip TLS verification | true (for dev) | false |
| `connectTimeout` | Connection timeout | 0s (disabled) | 30s |
| `tlsTimeout` | TLS handshake timeout | 0s (disabled) | 10s |
| `tcpKeepAlive` | TCP keep-alive interval | 0s (disabled) | 30s |
| `keepAliveTimeout` | Keep-alive timeout | 0s (disabled) | 90s |
| `http_status:404` | Catch-all for unmatched requests | Required | Required |

### 7.3 Validate Configuration
```cmd
cloudflared tunnel ingress validate
```
Should output: "OK"

---

## Step 8: Create DNS Route

This step creates the DNS record automatically in Cloudflare:

```cmd
cloudflared tunnel route dns my-app-tunnel domain.com
```

**Expected output:**
```
2024-01-15T10:30:45Z INF Added CNAME domain.com which will route to this tunnel tunnelID=6ff42ae2-765d-4adf-8112-31c55c1551ef
```

**What this does:**
- Automatically creates a CNAME record in Cloudflare DNS
- Points `domain.com` to `<tunnel-id>.cfargotunnel.com`
- Enables Cloudflare proxy (orange cloud)

**Verify in Dashboard:**
1. Go to Cloudflare Dashboard → DNS
2. You should see a new CNAME record for your domain
3. Proxy status should be "Proxied" (orange cloud)

---

## Step 9: Run the Tunnel

### 9.1 Test Run (Foreground)
Run this first to verify everything works:
```cmd
cloudflared tunnel run
```

**Expected output:**
```
2024-01-15T10:35:20Z INF Starting tunnel tunnelID=6ff42ae2-765d-4adf-8112-31c55c1551ef
2024-01-15T10:35:21Z INF Connection registered connIndex=0 location=DFW
2024-01-15T10:35:22Z INF Connection registered connIndex=1 location=DFW
2024-01-15T10:35:23Z INF Connection registered connIndex=2 location=IAD
2024-01-15T10:35:24Z INF Connection registered connIndex=3 location=IAD
```

**Use Ctrl+C to stop**

---

## Step 10: Test Your Setup

### 10.1 Local Test
```cmd
curl http://localhost:5000
```
Should return your application response.

### 10.2 External Access Test
From another network or mobile data:
```bash
curl https://domain.com
```
Should return the same response as localhost.

### 10.3 Browser Test
Open: `https://domain.com`

### 10.4 Dashboard Verification
1. Go to [Zero Trust Dashboard](https://one.dash.cloudflare.com)
2. Navigate to Networks → Tunnels
3. Your tunnel should show:
   - Status: **HEALTHY**
   - Connectors: 4 (default)

---

## Management Commands Reference

### Service Management
```powershell
# Stop service
Stop-Service Cloudflared

# Restart service (after config changes)
Restart-Service Cloudflared

# Uninstall service
cloudflared service uninstall
```

### Tunnel Management
```cmd
# List all tunnels
cloudflared tunnel list

# Show tunnel info
cloudflared tunnel info my-app-tunnel

# Delete tunnel (must stop service first)
cloudflared tunnel delete my-app-tunnel

# Update cloudflared
cloudflared update
```

### DNS Management
```cmd
# List routes
cloudflared tunnel route list
```

---

## Troubleshooting Guide

### Common Issues and Solutions

| Issue | Symptoms | Solution |
|-------|----------|----------|
| **Domain not active** | Cloudflare shows "Pending" | Wait for nameserver propagation (up to 48 hours) |
| **DNSSEC Error** | Domain won't activate | Disable DNSSEC at registrar, wait 30 minutes |
| **502 Bad Gateway** | Browser shows 502 error | Ensure your app is running on localhost:5000 |
| **404 Not Found** | Cloudflare 404 page | Check DNS records and ingress rules order |
| **Tunnel unhealthy** | Dashboard shows unhealthy | Check Windows Firewall, allow outbound 443/7844 |
| **Certificate errors** | Authentication failed | Re-run: `cloudflared tunnel login` |
| **Service won't start** | Service fails to start | Check Event Viewer → Windows Logs → Application |
| **ERR_TOO_MANY_REDIRECTS** | Redirect loop | Check SSL/TLS settings in Cloudflare (use Flexible or Full) |

### Debug Mode
Run with verbose logging:
```cmd
cloudflared --loglevel debug tunnel run
```

### Check Logs
```powershell
# Windows Event Viewer
Get-EventLog -LogName Application -Source Cloudflared -Newest 20

# Or check log file (if configured)
type C:\Users\%USERNAME%\.cloudflared\cloudflared.log
```

---

## Quick Setup Script (PowerShell)

Save as `setup-tunnel.ps1`:
```powershell
# Variables
$TUNNEL_NAME = "my-app-tunnel"
$DOMAIN = "domain.com"

# Install cloudflared
Write-Host "Installing cloudflared..." -ForegroundColor Green
winget install Cloudflare.cloudflared

# Authenticate
Write-Host "Authenticating..." -ForegroundColor Green
cloudflared tunnel login

# Create tunnel
Write-Host "Creating tunnel..." -ForegroundColor Green
$output = cloudflared tunnel create $TUNNEL_NAME
$tunnel_id = ($output | Select-String -Pattern "[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}").Matches[0].Value

Write-Host "Tunnel ID: $tunnel_id" -ForegroundColor Yellow

# Create config
Write-Host "Creating config..." -ForegroundColor Green
$config = @"
tunnel: $tunnel_id
credentials-file: C:\Users\$env:USERNAME\.cloudflared\$tunnel_id.json
protocol: quic

ingress:
  - hostname: $DOMAIN
    service: http://localhost:5000
    originRequest:
      connectTimeout: 0s
      tlsTimeout: 0s
      tcpKeepAlive: 0s
      keepAliveTimeout: 0s
      http2Origin: false
      httpHostHeader: $DOMAIN
      noTLSVerify: true
      disableChunkedEncoding: false
      keepAliveConnections: 100000000
      proxyConnectTimeout: 0s
      expectContinueTimeout: 0s
  - service: http_status:404
"@

$config | Out-File -FilePath "$env:USERPROFILE\.cloudflared\config.yml" -Encoding UTF8

# Create DNS route
Write-Host "Creating DNS route..." -ForegroundColor Green
cloudflared tunnel route dns $TUNNEL_NAME $DOMAIN

# Install service
Write-Host "Installing service..." -ForegroundColor Green
cloudflared service install

# Start service
Write-Host "Starting service..." -ForegroundColor Green
Start-Service Cloudflared

Write-Host "Setup complete! Your tunnel is running at https://$DOMAIN" -ForegroundColor Green
```
