# XMRig Proxy 401 UNAUTHORIZED Fix

## Problem
Dashboard shows no worker data and XMRig Proxy API returns:
```json
{
    "status": 401,
    "error": "UNAUTHORIZED"
}
```

## Root Cause
XMRig Proxy API requires authentication even when `"restricted": false` is set.

## Solutions

### Option 1: Disable Authentication (Recommended if proxy is locked down)

Since your proxy is already secured (only port 3333 exposed to internet, port 8080 only accessible from dashboard), you can disable API authentication.

**XMRig Proxy config.json:**
```json
{
    "http": {
        "enabled": true,
        "host": "0.0.0.0",
        "port": 8080,
        "access-token": null,
        "restricted": false
    }
}
```

**Then start XMRig Proxy with the no-auth flag:**
```bash
./xmrig-proxy --config=config.json --http-no-restricted
```

Or add to your systemd service file:
```ini
[Service]
ExecStart=/path/to/xmrig-proxy --config=/path/to/config.json --http-no-restricted
```

**Restart XMRig Proxy after making changes!**

### Option 2: Use Access Token (Better Security)

If you want to keep authentication enabled:

**1. Generate a secure token:**
```bash
openssl rand -hex 32
# Example output: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6
```

**2. Set in XMRig Proxy config.json:**
```json
{
    "http": {
        "enabled": true,
        "host": "0.0.0.0",
        "port": 8080,
        "access-token": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
        "restricted": true
    }
}
```

**3. Set in Dashboard docker-compose.yml:**
```yaml
dashboard:
  environment:
    - XMRIG_PROXY_HOSTS=auto
    - XMRIG_PROXY_TOKEN=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6
```

**4. Restart both:**
- XMRig Proxy
- Dashboard container

## Testing

### Test XMRig Proxy API without auth:
```bash
curl http://<proxy-ip>:8080/workers.json
```

Should return JSON with worker data (not 401 or 404 error).

Example response:
```json
{
    "hashrate": {
        "total": [0.1, 0.0, 0.0, 0.0, 0.0]
    },
    "workers": [
        ["worker1", "192.168.1.100", 1, 14, 0, 0, 28000, 1506315222361, 0.1, 0.0, 0.0, 0.0, 0.0]
    ]
}
```

### Test XMRig Proxy API with auth:
```bash
curl -H "Authorization: Bearer YOUR-TOKEN-HERE" http://<proxy-ip>:8080/workers.json
```

### Check Dashboard Logs:
```bash
docker logs dashboard -f
```

Look for:
- `Auto-detected proxy IPs: ['10.14.0.10', '10.14.0.20']`
- `Fetched X workers from Y proxies`

If you see:
- `ERROR: XMRig Proxy X.X.X.X returned 401 UNAUTHORIZED` → Auth issue
- `Error fetching XMRig Proxy workers from X.X.X.X` → Network/connectivity issue

## Recommended Setup (No Auth)

For your use case (proxy locked down, only dashboard can access port 8080):

**XMRig Proxy:**
```bash
./xmrig-proxy --config=config.json --http-no-restricted
```

**Dashboard:**
```yaml
environment:
  - XMRIG_PROXY_HOSTS=auto
  # No XMRIG_PROXY_TOKEN needed
```

This is simpler and secure enough since:
- Port 8080 is NOT exposed to internet
- Only dashboard can reach it
- Workers only connect to port 3333

## Verification Checklist

- [ ] XMRig Proxy HTTP API enabled (`"enabled": true`)
- [ ] XMRig Proxy listening on all interfaces (`"host": "0.0.0.0"`)
- [ ] XMRig Proxy port 8080 accessible from dashboard
- [ ] Either `--http-no-restricted` flag OR `XMRIG_PROXY_TOKEN` set
- [ ] XMRig Proxy restarted after config changes
- [ ] Dashboard has `XMRIG_PROXY_HOSTS=auto` environment variable
- [ ] Dashboard container rebuilt and restarted
- [ ] Dashboard logs show auto-detected proxy IPs
- [ ] Dashboard logs show fetched workers (not 401 errors)

