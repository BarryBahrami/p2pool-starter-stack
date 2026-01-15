# XMRig Proxy Integration for Dashboard

## Overview
The dashboard now supports fetching detailed per-worker stats from XMRig Proxy API, which is the **recommended approach** when using XMRig Proxy with thousands of workers.

## Architecture

### Before (Inefficient):
```
Workers (1000s) → XMRig Proxy → P2Pool
                                    ↓
                            Dashboard tries to query each worker directly
                            (1000s of failed HTTP requests every 30s)
```

### After (Optimized):
```
Workers (1000s) → XMRig Proxy → P2Pool (1 connection)
                       ↓
                  Dashboard queries proxy API
                  (1 HTTP request every 30s)
```

## Configuration

### 1. XMRig Proxy Settings

**For EACH proxy server**, configure:

#### a) Enable HTTP API
```json
{
    "http": {
        "enabled": true,
        "host": "0.0.0.0",  // Allow external access
        "port": 8080,
        "access-token": null,
        "restricted": true
    }
}
```

#### b) Aggregate Workers
```json
{
    "mode": "simple",
    "workers": false,  // ← IMPORTANT: Aggregate workers into one P2Pool connection
    "pools": [
        {
            "url": "10.14.0.5:3333",  // Your P2Pool IP
            "user": "europeproxy",
            ...
        }
    ]
}
```

**Restart ALL XMRig Proxy servers after changing configs!**

### 2. Dashboard Environment Variables

#### Option A: Auto-Detect (Recommended)
Dashboard automatically detects proxy IPs from P2Pool stratum stats:

```yaml
dashboard:
  environment:
    - XMRIG_PROXY_HOSTS=auto  # Auto-detect all proxies
```

#### Option B: Manual List
Specify proxy IPs manually (comma-separated):

```yaml
dashboard:
  environment:
    - XMRIG_PROXY_HOSTS=10.14.0.10,10.14.0.20,10.14.0.30
```

#### Option C: Disable Proxy Stats
Use only P2Pool stratum stats:

```yaml
dashboard:
  environment:
    - XMRIG_PROXY_HOSTS=none
```

## How It Works

### Data Sources (Priority Order):

1. **XMRig Proxy API** (if `XMRIG_PROXY_HOST` is set)
   - Queries `http://<proxy>:8080/2/backends` for per-worker stats
   - Gets real-time hashrate (10s, 60s, 15m), uptime, shares for ALL workers
   - ✅ **Best for thousands of workers**

2. **Direct Worker API Polling** (if `ENABLE_WORKER_API_POLLING=true`)
   - Queries each worker's XMRig API directly
   - ⚠️ **Not recommended** - creates thousands of HTTP requests
   - Only use if workers expose port 8080 and you have <100 workers

3. **P2Pool Stratum Stats** (fallback)
   - Reads `/app/stats/local/stratum` file
   - Basic stats from P2Pool's perspective
   - ⚡ **Fast but limited data** when using proxy with `workers: false`

## XMRig Proxy API Endpoints

The dashboard uses:
- `GET http://<proxy>:8080/2/backends` - Per-worker detailed stats

Other useful endpoints:
- `GET http://<proxy>:8080/1/summary` - Aggregate proxy stats
- `GET http://<proxy>:8080/1/config` - Proxy configuration

## System Requirements for Thousands of Workers

### On XMRig Proxy Host:
```bash
# Increase file descriptor limit (for thousands of worker connections)
ulimit -n 65535

# Make permanent in /etc/security/limits.conf
echo "* soft nofile 65535" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65535" | sudo tee -a /etc/security/limits.conf
```

### On P2Pool Host:
No changes needed! With `workers: false`, proxy creates only 1 connection to P2Pool.

## Dashboard Status Indicators

The dashboard shows which data source is active:

- **📊 XMRig Proxy Stats** - Using proxy API (recommended)
- **⚡ P2Pool Stats Only** - Using P2Pool stratum file (basic)
- **⚠ Direct Worker API Polling** - Querying individual workers (not recommended for scale)

## Troubleshooting

### Workers not showing up:
1. Check XMRig Proxy is running: `curl http://<proxy>:8080/1/summary`
2. Verify `XMRIG_PROXY_HOST` is set correctly
3. Check dashboard logs for errors

### Proxy shows 0 workers:
1. Verify workers are connecting to proxy
2. Check proxy logs: `./xmrig-proxy --verbose`
3. Ensure `workers: false` is set and proxy was restarted

### Dashboard shows "P2Pool Stats Only":
1. `XMRIG_PROXY_HOST` environment variable not set
2. Proxy API not reachable from dashboard container
3. Check network connectivity: `docker exec dashboard curl http://<proxy>:8080/1/summary`

## Performance

With this setup:
- ✅ Dashboard: 1 HTTP request per 30 seconds (regardless of worker count)
- ✅ XMRig Proxy: Handles thousands of worker connections efficiently
- ✅ P2Pool: Sees only 1 connection from proxy (minimal load)
- ✅ Workers: Get individual stats tracked by proxy

## Example docker-compose.yml

```yaml
dashboard:
  build: ./build/dashboard
  container_name: dashboard
  restart: unless-stopped
  environment:
    - XMRIG_PROXY_HOSTS=auto  # Auto-detect all proxies (recommended)
    # OR manually specify: - XMRIG_PROXY_HOSTS=10.14.0.10,10.14.0.20,10.14.0.30
  volumes:
    - ./data/p2pool/stats:/app/stats:ro
    - ./data/monero:/app/logs/monero:ro
    - ./data/tari:/app/logs/tari:ro
    - /home:/data:ro
    - /var/run/docker.sock:/var/run/docker.sock:ro
  network_mode: "host"
```

## Multiple Proxy Architecture

```
Workers (EU Region)     → XMRig Proxy 1 (10.14.0.10) ─┐
Workers (US Region)     → XMRig Proxy 2 (10.14.0.20) ─┼→ P2Pool (10.14.0.5)
Workers (Asia Region)   → XMRig Proxy 3 (10.14.0.30) ─┘
                                ↓           ↓           ↓
                          Dashboard queries all 3 proxy APIs
                          (3 HTTP requests every 30s total)
```

**Benefits:**
- Each proxy aggregates its workers into 1 P2Pool connection
- Dashboard queries all proxies in parallel
- Scales to unlimited workers across multiple regions
- P2Pool only sees 3 connections (not thousands)

