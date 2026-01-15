# XMRig Proxy Aggregate Stats Dashboard

## Overview

When you set `"workers": false` in XMRig Proxy config, the proxy aggregates all workers into a single connection to P2Pool. The dashboard now queries each proxy's `/2/summary` endpoint to get aggregate stats.

## How It Works

```
Workers → XMRig Proxy 1 (10.14.0.4) → P2Pool
Workers → XMRig Proxy 2 (10.14.2.4) → P2Pool
              ↓                ↓
        Dashboard queries both proxies
        Shows aggregate stats per proxy
```

## Dashboard Display

The dashboard will show:
- **Each proxy as a "worker group"**
- **Proxy name** (e.g., "westusproxy", "eastusproxy")
- **Proxy IP** (e.g., "10.14.0.4")
- **Aggregate hashrate** (10s, 15m, 1h)
- **Miners connected** (e.g., "7/7" = 7 current, 7 max)
- **Shares** (accepted/rejected)
- **Uptime**

## P2Pool Verification

The dashboard compares:
1. **Proxy aggregate hashrate** (from `/2/summary`)
2. **P2Pool reported hashrate** (from `/stats/local/stratum`)

This confirms P2Pool is receiving and processing shares from all proxies.

## Configuration

### XMRig Proxy (on each proxy server)

```json
{
    "workers": false,  // Aggregate workers into one P2Pool connection
    "http": {
        "enabled": true,
        "host": "0.0.0.0",
        "port": 8080,
        "access-token": null,
        "restricted": false
    },
    "pools": [
        {
            "url": "20.163.2.161:3333",  // Your P2Pool IP
            "user": "westusproxy",       // Proxy name (shows in dashboard)
            ...
        }
    ]
}
```

### Dashboard (docker-compose.yml)

```yaml
dashboard:
  environment:
    - XMRIG_PROXY_HOSTS=auto  # Auto-detect proxy IPs from P2Pool
```

## After Configuration

1. **Restart all XMRig Proxies** (to apply `"workers": false`)
2. **Restart P2Pool** (to clear old connections)
3. **Rebuild and restart Dashboard**

```bash
./build-and-run.sh
```

## Expected Result

### Before (workers: true):
- P2Pool sees: 100 connections (one per worker)
- Dashboard shows: 100 individual workers

### After (workers: false):
- P2Pool sees: 2 connections (one per proxy)
- Dashboard shows: 2 proxy groups with aggregate stats
- Each proxy group shows total hashrate from all its workers

## Verification

### Check P2Pool sees proxies:
```bash
ssh xmr@20.163.2.161
cat ~/p2pool-starter-stack/data/p2pool/stats/local/stratum | python3 -m json.tool
```

Should show:
```json
{
  "connections": 2,
  "workers": [
    "10.14.0.4:xxxxx,uptime,hashes,shares,westusproxy",
    "10.14.2.4:xxxxx,uptime,hashes,shares,eastusproxy"
  ]
}
```

### Check proxy stats:
```bash
wget -q -O- http://10.14.0.4:8080/2/summary | python3 -m json.tool
```

Should show:
```json
{
  "worker_id": "westusproxy",
  "miners": {"now": 7, "max": 7},
  "hashrate": {"total": [13.28, 9.15, 1.52, 0.12, 0.06, 16.54]},
  ...
}
```

### Check dashboard:
```
http://your-dashboard-ip:8000
```

Should show:
- **Worker Groups: 2**
- **westusproxy** - 10.14.0.4 - 7/7 miners - 16.54 H/s
- **eastusproxy** - 10.14.2.4 - X/X miners - X.XX H/s

## Troubleshooting

### Dashboard shows 0 workers
- Check proxy API is accessible: `wget http://proxy-ip:8080/2/summary`
- Check dashboard logs: `docker logs dashboard -f`
- Verify `XMRIG_PROXY_HOSTS=auto` is set

### P2Pool still shows many connections
- **Restart P2Pool** to clear old connections
- Verify proxies have `"workers": false` in config
- Verify proxies were restarted after config change

### Hashrate mismatch between proxy and P2Pool
- Normal - P2Pool calculates based on shares submitted
- Proxy shows miner-reported hashrate
- Should be within 10-20% of each other

