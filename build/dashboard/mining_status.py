import json
import os
import shutil
import time
import asyncio
import subprocess
from aiohttp import web, ClientSession, ClientTimeout
from datetime import timedelta
from collections import defaultdict

# --- CONFIGURATION ---
STRATUM_STATS_PATH = "/app/stats/local/stratum"
TARI_STATS_PATH = "/app/stats/local/merge_mining"
P2POOL_STATS_PATH = "/app/stats/local/stats"
DISK_PATH = '/data'
XMRIG_API_PORT = 8080
API_TIMEOUT = 1
UPDATE_INTERVAL = 30  # Refresh background data every 30 seconds
LOG_LINES = 100  # Number of log lines to fetch

# XMRig Proxy API (optional) - set to enable proxy stats
# Can be a single host or comma-separated list: "10.14.0.10,10.14.0.20,10.14.0.30"
# Or set to "auto" to auto-detect from P2Pool stratum stats
XMRIG_PROXY_HOSTS = os.environ.get("XMRIG_PROXY_HOSTS", "auto")
XMRIG_PROXY_TOKEN = os.environ.get("XMRIG_PROXY_TOKEN", None)  # Access token for XMRig Proxy API
ENABLE_WORKER_API_POLLING = os.environ.get("ENABLE_WORKER_API_POLLING", "false").lower() == "true"

LATEST_DATA = {}
HASHRATE_HISTORY = []

def format_hr(h):
    try:
        val = float(h)
        if val >= 1000000000: return f"{val/1000000000:.2f} GH/s"
        if val >= 1000000: return f"{val/1000000:.2f} MH/s"
        if val >= 1000: return f"{val/1000:.2f} KH/s"
        return f"{val:.2f} H/s"
    except: return "0 H/s"

def format_uptime(seconds):
    try: return str(timedelta(seconds=int(seconds)))
    except: return "Unknown"

async def get_worker_live_stats(session, name, ip_with_port):
    """Query individual worker's XMRig API (only used if ENABLE_WORKER_API_POLLING=true)"""
    ip = ip_with_port.split(':')[0]
    targets = [name, ip]
    timeout = ClientTimeout(total=API_TIMEOUT)

    for target in targets:
        url = f"http://{target}:{XMRIG_API_PORT}/1/summary"
        try:
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    hr_obj = data.get("hashrate", {})
                    hashrates = hr_obj.get("total", [0, 0, 0])
                    return {
                        "h10": hashrates[0] if len(hashrates) > 0 else 0,
                        "h60": hashrates[1] if len(hashrates) > 1 else 0,
                        "h15": hashrates[2] if len(hashrates) > 2 else 0,
                        "uptime": data.get("uptime", 0),
                        "name": data.get("worker_id", "miner")
                    }
        except: continue
    return None

async def get_xmrig_proxy_summary(session, proxy_host):
    """Query a single XMRig Proxy API for aggregate stats"""
    url = f"http://{proxy_host}:{XMRIG_API_PORT}/2/summary"
    timeout = ClientTimeout(total=API_TIMEOUT * 3)

    # Prepare headers with access token if configured
    headers = {}
    if XMRIG_PROXY_TOKEN:
        headers['Authorization'] = f'Bearer {XMRIG_PROXY_TOKEN}'

    try:
        async with session.get(url, headers=headers, timeout=timeout) as response:
            if response.status == 401:
                print(f"ERROR: XMRig Proxy {proxy_host} returned 401 UNAUTHORIZED.", flush=True)
                return None
            if response.status == 200:
                data = await response.json()
                # Extract aggregate stats from proxy
                hashrate = data.get("hashrate", {}).get("total", [0, 0, 0, 0, 0, 0])
                return {
                    "proxy_host": proxy_host,
                    "worker_id": data.get("worker_id", "unknown"),
                    "uptime": data.get("uptime", 0),
                    "miners_now": data.get("miners", {}).get("now", 0),
                    "miners_max": data.get("miners", {}).get("max", 0),
                    "h10s": hashrate[0] if len(hashrate) > 0 else 0,
                    "h1m": hashrate[1] if len(hashrate) > 1 else 0,
                    "h15m": hashrate[2] if len(hashrate) > 2 else 0,
                    "h1h": hashrate[3] if len(hashrate) > 3 else 0,
                    "h12h": hashrate[4] if len(hashrate) > 4 else 0,
                    "h24h": hashrate[5] if len(hashrate) > 5 else 0,
                    "accepted": data.get("results", {}).get("accepted", 0),
                    "rejected": data.get("results", {}).get("rejected", 0),
                    "version": data.get("version", "unknown")
                }
            else:
                print(f"XMRig Proxy {proxy_host} returned status {response.status}", flush=True)
    except Exception as e:
        print(f"Error fetching XMRig Proxy summary from {proxy_host}: {e}", flush=True)
    return None

async def get_xmrig_proxy_summary(session, proxy_host):
    """Query a single XMRig Proxy API for aggregate stats"""
    url = f"http://{proxy_host}:{XMRIG_API_PORT}/2/summary"
    timeout = ClientTimeout(total=API_TIMEOUT * 3)

    # Prepare headers with access token if configured
    headers = {}
    if XMRIG_PROXY_TOKEN:
        headers['Authorization'] = f'Bearer {XMRIG_PROXY_TOKEN}'

    try:
        async with session.get(url, headers=headers, timeout=timeout) as response:
            if response.status == 401:
                print(f"ERROR: XMRig Proxy {proxy_host} returned 401 UNAUTHORIZED.", flush=True)
                return None
            if response.status == 200:
                data = await response.json()
                # Extract aggregate stats from proxy
                hashrate = data.get("hashrate", {}).get("total", [0, 0, 0, 0, 0, 0])
                return {
                    "proxy_host": proxy_host,
                    "worker_id": data.get("worker_id", "unknown"),
                    "uptime": data.get("uptime", 0),
                    "miners_now": data.get("miners", {}).get("now", 0),
                    "miners_max": data.get("miners", {}).get("max", 0),
                    "h10s": hashrate[0] if len(hashrate) > 0 else 0,
                    "h1m": hashrate[1] if len(hashrate) > 1 else 0,
                    "h15m": hashrate[2] if len(hashrate) > 2 else 0,
                    "h1h": hashrate[3] if len(hashrate) > 3 else 0,
                    "h12h": hashrate[4] if len(hashrate) > 4 else 0,
                    "h24h": hashrate[5] if len(hashrate) > 5 else 0,
                    "accepted": data.get("results", {}).get("accepted", 0),
                    "rejected": data.get("results", {}).get("rejected", 0),
                    "version": data.get("version", "unknown")
                }
            else:
                print(f"XMRig Proxy {proxy_host} returned status {response.status}", flush=True)
    except Exception as e:
        print(f"Error fetching XMRig Proxy summary from {proxy_host}: {e}", flush=True)
    return None

async def get_all_proxy_summaries(session, proxy_hosts):
    """Query multiple XMRig Proxy servers for aggregate stats"""
    if not proxy_hosts:
        return []

    tasks = []
    for proxy_host in proxy_hosts:
        tasks.append(get_xmrig_proxy_summary(session, proxy_host.strip()))

    results = await asyncio.gather(*tasks)

    # Filter out None results
    return [r for r in results if r is not None]

def get_disk_usage(path="/"):
    try:
        usage = shutil.disk_usage(path)
        percent = (usage.used / usage.total) * 100
        return {
            "total": f"{usage.total / (1024**3):.1f} GB",
            "used": f"{usage.used / (1024**3):.1f} GB",
            "percent": f"{percent:.1f}%",
            "percent_val": percent
        }
    except: return {"total": "N/A", "used": "N/A", "percent": "0%", "percent_val": 0}

def get_container_logs(container_name, lines=100):
    """Fetch logs from a Docker container or log files."""

    # Map container names to log file paths
    log_file_map = {
        'monerod': '/app/logs/monero/bitmonero.log',
        'tari': '/app/logs/tari/mainnet/log/base_node/base_layer.log',
        'p2pool': None  # P2Pool only logs to stdout
    }

    # Try Docker logs first
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            output = result.stdout + result.stderr
            if output.strip():
                return output
    except:
        pass  # Fall through to file-based approach

    # Fall back to reading log files if available
    log_file = log_file_map.get(container_name)
    if log_file and os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                # Read last N lines efficiently
                all_lines = f.readlines()
                last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                return ''.join(last_lines)
        except Exception as e:
            return f"Error reading log file {log_file}: {str(e)}"

    # If all else fails
    return f"Unable to fetch logs for {container_name}. Docker logs not accessible and no log file found."

async def update_data_loop():
    """Background task to fetch stats and update chart history."""
    global LATEST_DATA, HASHRATE_HISTORY

    # Log optimization settings on startup
    print(f"=== Dashboard Optimization Settings ===", flush=True)
    print(f"Worker API Polling: {'ENABLED' if ENABLE_WORKER_API_POLLING else 'DISABLED (Optimized for thousands of workers)'}", flush=True)
    print(f"XMRig Proxy Hosts: {XMRIG_PROXY_HOSTS}", flush=True)
    print(f"Update Interval: {UPDATE_INTERVAL}s", flush=True)
    print(f"======================================", flush=True)

    while True:
        data = {
            "host_ip": os.environ.get("HOST_IP", "Unknown Host"),
            "now": time.strftime('%Y-%m-%d %H:%M:%S'),
            "system": {"hp_status": "Unknown", "hp_val": "0/0", "hp_class": "status-warn"},
            "disk": get_disk_usage(DISK_PATH),
            "tari": None,
            "stratum": {},
            "workers": [],
            "worker_groups": {},
            "total_live_h10": 0,
            "total_live_h15": 0,
            "blocks_found": {"monero": 0, "tari": 0}
        }

        # 1. Huge Pages
        try:
            with open("/proc/meminfo", "r") as f:
                mem = f.read()
            hp_total = int([l for l in mem.split('\n') if "HugePages_Total" in l][0].split()[1])
            hp_free = int([l for l in mem.split('\n') if "HugePages_Free" in l][0].split()[1])
            data["system"]["hp_val"] = f"{hp_total - hp_free} / {hp_total}"
            if (hp_total - hp_free) > 500:
                data["system"]["hp_status"], data["system"]["hp_class"] = "HEALTHY", "status-ok"
            else:
                data["system"]["hp_status"], data["system"]["hp_class"] = "NOT DETECTED", "status-bad"
        except: pass

        # 2. Tari Stats
        if os.path.exists(TARI_STATS_PATH):
            try:
                with open(TARI_STATS_PATH, 'r') as f:
                    t_json = json.load(f)
                    chains = t_json.get("chains", [])
                    if chains:
                        t = chains[0]
                        data["tari"] = {
                            "status": t.get('channel_state', 'UNKNOWN'),
                            "address": t.get('wallet', 'Unknown'),
                            "height": t.get('height', 0),
                            "reward": t.get('reward', 0) / 1_000_000,
                            "diff": f"{t.get('difficulty', 0):,}"
                        }
            except: pass

        # 3. Stratum & Worker Processing (optimized for thousands of workers)
        if os.path.exists(STRATUM_STATS_PATH):
            try:
                with open(STRATUM_STATS_PATH, 'r') as f:
                    s_json = json.load(f)
                    data["stratum"] = s_json

                    # Build worker groups during processing (single pass optimization)
                    worker_groups = defaultdict(lambda: {"workers": [], "total_h15": 0, "online_count": 0, "total_count": 0})

                    # Determine which proxy hosts to query
                    proxy_hosts_to_query = []
                    if XMRIG_PROXY_HOSTS and XMRIG_PROXY_HOSTS.lower() != "none":
                        if XMRIG_PROXY_HOSTS.lower() == "auto":
                            # Auto-detect: Extract unique IPs from P2Pool stratum worker list
                            seen_ips = set()
                            for w_entry in s_json.get("workers", []):
                                if isinstance(w_entry, str):
                                    parts = w_entry.split(',')
                                    ip_with_port = parts[0]  # Format: "ip:port"
                                    ip = ip_with_port.split(':')[0]
                                    seen_ips.add(ip)
                            proxy_hosts_to_query = list(seen_ips)
                            print(f"Auto-detected proxy IPs: {proxy_hosts_to_query}", flush=True)
                        else:
                            # Manual list: comma-separated
                            proxy_hosts_to_query = [h.strip() for h in XMRIG_PROXY_HOSTS.split(',')]
                            print(f"Using configured proxy hosts: {proxy_hosts_to_query}", flush=True)

                    # Check if we should use XMRig Proxy API for aggregate stats
                    if proxy_hosts_to_query:
                        # Use XMRig Proxy API to get aggregate stats from all proxies
                        async with ClientSession() as session:
                            all_proxy_summaries = await get_all_proxy_summaries(session, proxy_hosts_to_query)

                            if all_proxy_summaries:
                                print(f"Fetched stats from {len(all_proxy_summaries)} proxies", flush=True)
                                for proxy in all_proxy_summaries:
                                    w_data = {
                                        "name": proxy['worker_id'],
                                        "ip": proxy['proxy_host'],
                                        "status": "online",
                                        "up": format_uptime(proxy['uptime']),
                                        "h10": format_hr(proxy['h10s']),
                                        "h60": format_hr(proxy['h1h']),
                                        "h15": format_hr(proxy['h15m']),
                                        "h10_raw": proxy['h10s'],
                                        "h60_raw": proxy['h1h'],
                                        "h15_raw": proxy['h15m'],
                                        "miners": f"{proxy['miners_now']}/{proxy['miners_max']}",
                                        "accepted": proxy['accepted'],
                                        "rejected": proxy['rejected']
                                    }

                                    # Add to totals
                                    data["total_live_h10"] += proxy['h10s']
                                    data["total_live_h15"] += proxy['h15m']

                                    # Add to workers list and group (each proxy is a "group")
                                    data["workers"].append(w_data)
                                    group_name = proxy['worker_id']
                                    worker_groups[group_name]["workers"].append(w_data)
                                    worker_groups[group_name]["total_h15"] += proxy['h15m']
                                    worker_groups[group_name]["total_count"] += 1
                                    worker_groups[group_name]["online_count"] += 1
                            else:
                                print(f"Failed to fetch from XMRig Proxies, falling back to P2Pool stats", flush=True)

                    # Fallback: Only poll individual worker APIs if explicitly enabled (disabled by default)
                    elif ENABLE_WORKER_API_POLLING:
                        async with ClientSession() as session:
                            tasks = []
                            worker_meta = []
                            for w_entry in s_json.get("workers", []):
                                if isinstance(w_entry, str):
                                    parts = w_entry.split(',')
                                    # P2Pool stratum stats format: [0]=ip:port, [1]=uptime, [2]=h10s, [3]=h60s, [4]=name
                                    ip_label = parts[0]
                                    name = parts[4] if len(parts) >= 5 else "miner"
                                    worker_meta.append({'parts': parts, 'ip': ip_label, 'name': name})
                                    tasks.append(get_worker_live_stats(session, name, ip_label))

                            results = await asyncio.gather(*tasks)

                            for meta, live in zip(worker_meta, results):
                                if live:
                                    w_data = {
                                        "name": meta['name'], "ip": meta['ip'], "status": "online",
                                        "up": format_uptime(live['uptime']),
                                        "h10": format_hr(live['h10']), "h60": format_hr(live['h60']), "h15": format_hr(live['h15']),
                                        "h10_raw": live['h10'], "h60_raw": live['h60'], "h15_raw": live['h15']
                                    }
                                    data["total_live_h10"] += (live['h10'] or 0)
                                    data["total_live_h15"] += (live['h15'] or 0)
                                else:
                                    # Worker API not reachable - use stratum stats
                                    parts = meta['parts']
                                    raw_h10 = float(parts[2]) if len(parts) >= 3 else 0
                                    raw_h60 = float(parts[3]) if len(parts) >= 4 else 0
                                    raw_h15 = raw_h60  # Use 60s as estimate for 15m

                                    w_data = {
                                        "name": meta['name'], "ip": meta['ip'], "status": "offline",
                                        "up": format_uptime(parts[1]) if len(parts) >= 2 else "0",
                                        "h10": format_hr(raw_h10) if raw_h10 > 0 else "-",
                                        "h60": format_hr(raw_h60) if raw_h60 > 0 else "-",
                                        "h15": format_hr(raw_h15) if raw_h15 > 0 else "-",
                                        "h10_raw": raw_h10, "h60_raw": raw_h60, "h15_raw": raw_h15
                                    }
                                    data["total_live_h10"] += raw_h10
                                    data["total_live_h15"] += raw_h15

                                # Add to workers list and group (single pass)
                                data["workers"].append(w_data)
                                group_name = w_data["name"]
                                worker_groups[group_name]["workers"].append(w_data)
                                worker_groups[group_name]["total_h15"] += w_data["h15_raw"]
                                worker_groups[group_name]["total_count"] += 1
                                if w_data["status"] == "online":
                                    worker_groups[group_name]["online_count"] += 1
                    else:
                        # Fast path: Use only P2Pool stratum stats (no API polling)
                        # This is the recommended mode for thousands of workers
                        for w_entry in s_json.get("workers", []):
                            if isinstance(w_entry, str):
                                parts = w_entry.split(',')
                                # P2Pool stratum format: [0]=ip:port, [1]=uptime, [2]=h10s, [3]=h60s, [4]=name
                                ip_label = parts[0]
                                name = parts[4] if len(parts) >= 5 else "miner"

                                raw_h10 = float(parts[2]) if len(parts) >= 3 else 0
                                raw_h60 = float(parts[3]) if len(parts) >= 4 else 0
                                raw_h15 = raw_h60  # Use 60s as estimate for 15m

                                w_data = {
                                    "name": name, "ip": ip_label, "status": "active",
                                    "up": format_uptime(parts[1]) if len(parts) >= 2 else "0",
                                    "h10": format_hr(raw_h10) if raw_h10 > 0 else "-",
                                    "h60": format_hr(raw_h60) if raw_h60 > 0 else "-",
                                    "h15": format_hr(raw_h15) if raw_h15 > 0 else "-",
                                    "h10_raw": raw_h10, "h60_raw": raw_h60, "h15_raw": raw_h15
                                }

                                # Add to totals
                                data["total_live_h10"] += raw_h10
                                data["total_live_h15"] += raw_h15

                                # Add to workers list and group (single pass)
                                data["workers"].append(w_data)
                                group_name = name
                                worker_groups[group_name]["workers"].append(w_data)
                                worker_groups[group_name]["total_h15"] += raw_h15
                                worker_groups[group_name]["total_count"] += 1
                                worker_groups[group_name]["online_count"] += 1  # All workers in stratum are active

                    data["worker_groups"] = dict(worker_groups)
            except: pass

        # 5. P2Pool Stats for blocks found
        if os.path.exists(P2POOL_STATS_PATH):
            try:
                with open(P2POOL_STATS_PATH, 'r') as f:
                    p2pool_json = json.load(f)
                    data["blocks_found"]["monero"] = p2pool_json.get("pool_statistics", {}).get("totalBlocksFound", 0)
            except: pass

        # 6. Tari blocks found (from merge mining stats)
        if data["tari"]:
            try:
                with open(TARI_STATS_PATH, 'r') as f:
                    t_json = json.load(f)
                    chains = t_json.get("chains", [])
                    if chains:
                        data["blocks_found"]["tari"] = chains[0].get("blocks_mined", 0)
            except: pass

        # Update History Chart (use 15m for stable chart)
        print(f"Workers: {len(data['workers'])}, Groups: {len(data['worker_groups'])}, H10: {format_hr(data['total_live_h10'])}, H15: {format_hr(data['total_live_h15'])}", flush=True)
        HASHRATE_HISTORY.append({"t": time.strftime('%H:%M'), "v": data["total_live_h15"]})
        if len(HASHRATE_HISTORY) > 30: HASHRATE_HISTORY.pop(0)

        LATEST_DATA = data
        await asyncio.sleep(UPDATE_INTERVAL)

async def handle_get(request):
    d = LATEST_DATA
    if not d:
        return web.Response(text="Initializing data...", status=503)

    # Build worker group rows with expandable sub-rows
    group_rows = []
    for group_name, group_data in sorted(d["worker_groups"].items()):
        total_workers = group_data["total_count"]
        online_workers = group_data["online_count"]
        total_h15 = group_data["total_h15"]

        # Group header row
        group_rows.append(f"""
        <tr class="group-header" onclick="toggleGroup('{group_name}')">
            <td><span class="dot {'online' if online_workers > 0 else 'offline'}"></span>
                <strong>{group_name}</strong> <span style="color:#8b949e">({online_workers}/{total_workers})</span>
                <span class="expand-icon" id="icon-{group_name}">▶</span>
            </td>
            <td colspan="2">-</td>
            <td colspan="2">-</td>
            <td class="bold">{format_hr(total_h15)}</td>
        </tr>""")

        # Individual worker rows (hidden by default)
        for worker in group_data["workers"]:
            group_rows.append(f"""
        <tr class="worker-detail" data-group="{group_name}" style="display:none">
            <td style="padding-left:30px"><span class="dot {worker['status']}"></span>{worker['name']}</td>
            <td>{worker['ip']}</td>
            <td>{worker['up']}</td>
            <td>{worker['h10']}</td>
            <td>{worker['h60']}</td>
            <td class="bold">{worker['h15']}</td>
        </tr>""")

    rows = "".join(group_rows)

    # Blocks found section
    blocks_section = f"""
        <div class="stat-card">
            <h5>Blocks Found</h5>
            <p style="font-size: 13px; line-height: 1.6;">
                <strong>Monero:</strong> {d['blocks_found']['monero']}<br>
                <strong>Tari:</strong> {d['blocks_found']['tari']}
            </p>
        </div>"""

    tari_section = f"""
        <div class="card">
            <h3>Tari Merge Mining</h3>
            <div class="stat-grid">
                <div class="stat-card"><h5>Status</h5><p>{d['tari']['status']}</p></div>
                <div class="stat-card"><h5>Reward</h5><p>{d['tari']['reward']:.2f} TARI</p></div>
                <div class="stat-card"><h5>Height</h5><p>{d['tari']['height']}</p></div>
                <div class="stat-card"><h5>Difficulty</h5><p>{d['tari']['diff']}</p></div>
            </div>
            <div style="font-size:10px; color:#666; margin-top:10px; overflow-wrap: break-word;">Wallet: {d['tari']['address']}</div>
        </div>""" if d['tari'] else '<div class="card"><h3>Tari</h3><p>Waiting for data...</p></div>'

    html = f"""
    <!DOCTYPE html><html><head><title>Mining Dashboard</title><meta http-equiv="refresh" content="30">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; --ok: #238636; --bad: #da3633; --warn: #d29922; }}
        body {{ font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); padding: 20px; }}
        .container {{ max-width: 1200px; margin: auto; }}
        .header {{ display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; margin-bottom: 20px; }}
        .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 15px; }}
        h3 {{ margin: 0 0 15px 0; font-size: 14px; text-transform: uppercase; color: #8b949e; }}
        .stat-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
        .stat-card {{ background: #0d1117; padding: 10px; border-radius: 4px; border: 1px solid var(--border); }}
        .stat-card h5 {{ margin: 0; font-size: 10px; color: #8b949e; }}
        .stat-card p {{ margin: 5px 0 0 0; font-weight: bold; font-size: 16px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; font-size: 12px; color: #8b949e; padding: 10px; border-bottom: 1px solid var(--border); }}
        td {{ padding: 10px; border-bottom: 1px solid #21262d; font-size: 13px; }}
        .dot {{ height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 8px; }}
        .online {{ background: var(--ok); box-shadow: 0 0 5px var(--ok); }}
        .active {{ background: var(--ok); box-shadow: 0 0 5px var(--ok); }}
        .offline {{ background: var(--bad); }}
        .status-ok {{ color: var(--ok); }} .status-bad {{ color: var(--bad); }} .status-warn {{ color: var(--warn); }}
        .bold {{ font-weight: bold; color: var(--accent); }}
        .progress-bg {{ background: var(--border); border-radius: 4px; height: 10px; width: 100%; margin-top: 5px; }}
        .progress-fill {{ background: var(--accent); height: 100%; border-radius: 4px; transition: width 0.5s; }}
        .progress-fill.warning {{ background: var(--warn); }} .progress-fill.critical {{ background: var(--bad); }}
        .group-header {{ cursor: pointer; background: #1c2128; }}
        .group-header:hover {{ background: #22272e; }}
        .expand-icon {{ float: right; transition: transform 0.2s; }}
        .expand-icon.expanded {{ transform: rotate(90deg); }}
        .tabs {{ display: flex; gap: 10px; margin-bottom: 15px; border-bottom: 1px solid var(--border); }}
        .tab {{ padding: 10px 20px; cursor: pointer; border-bottom: 2px solid transparent; color: #8b949e; }}
        .tab.active {{ border-bottom-color: var(--accent); color: var(--accent); }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        .log-viewer {{ background: #0d1117; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 11px;
                       max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-wrap: break-word; }}
    </style></head>
    <body><div class="container">
        <div class="header">
            <div>
                <h2 style="margin:0">{d['host_ip']}</h2>
                <span class="{d['system']['hp_class']}">Huge Pages: {d['system']['hp_status']} ({d['system']['hp_val']})</span>
                <div style="margin-top: 5px; font-size: 12px; color: #8b949e;">
                    Disk: {d['disk']['used']} / {d['disk']['total']} ({d['disk']['percent']})
                    <div class="progress-bg"><div class="progress-fill {'critical' if d['disk']['percent_val'] > 90 else 'warning' if d['disk']['percent_val'] > 75 else ''}" style="width: {d['disk']['percent']}"></div></div>
                </div>
            </div>
            <div style="text-align: right">
                <div id="current-hashrate" style="font-size: 18px; font-weight: bold;">{format_hr(d['total_live_h15'])}</div>
                <small style="color:#8b949e">Last Update: {d['now']}</small>
            </div>
        </div>
        <div class="grid">
            <div class="card"><canvas id="hChart" height="180"></canvas></div>
            <div class="card">
                <h3>Stratum Pool</h3>
                <div class="stat-grid">
                    <div class="stat-card">
                        <h5>Hashrate Statistics</h5>
                        <p style="font-size: 11px; line-height: 1.4;">
                            <strong>15m:</strong> {format_hr(d['stratum'].get('hashrate_15m'))}<br>
                            <strong>1h:</strong> {format_hr(d['stratum'].get('hashrate_1h'))}<br>
                            <strong>24h:</strong> {format_hr(d['stratum'].get('hashrate_24h'))}
                        </p>
                    </div>
                    <div class="stat-card">
                        <h5>Shares (P/Err)</h5>
                        <p>{d['stratum'].get('shares_found', 0)} / {d['stratum'].get('shares_failed',0)}</p>
                    </div>
                    <div class="stat-card"><h5>Effort (Curr/Avg)</h5><p>{d['stratum'].get('current_effort',0):.2f}% / {d['stratum'].get('average_effort',0):.2f}%</p></div>
                    {blocks_section}
                </div>
                <div style="font-size:10px; color:#666; margin-top:10px; overflow-wrap: break-word;">Wallet: {d['stratum'].get('wallet', 'N/A')}</div>
            </div>
            {tari_section}
        </div>
        <div class="card">
            <h3>Worker Groups: {len(d['worker_groups'])} (Total Workers: {len(d['workers'])})
            {'<span style="color:#58a6ff; font-size:10px; margin-left:10px;">📊 XMRig Proxy Stats</span>' if XMRIG_PROXY_HOSTS and XMRIG_PROXY_HOSTS.lower() not in ['none', ''] else '<span style="color:#8b949e; font-size:10px; margin-left:10px;">⚡ P2Pool Stats Only</span>' if not ENABLE_WORKER_API_POLLING else '<span style="color:#f0883e; font-size:10px; margin-left:10px;">⚠ Direct Worker API Polling</span>'}
            </h3>
            <table><thead><tr><th>Worker Group</th><th>IP</th><th>Uptime</th><th>10s</th><th>60s</th><th>15m</th></tr></thead><tbody>{rows}</tbody></table>
        </div>
        <div class="card">
            <h3>Container Logs</h3>
            <div class="tabs">
                <div class="tab active" onclick="switchTab('monero')">Monero</div>
                <div class="tab" onclick="switchTab('tari')">Tari</div>
                <div class="tab" onclick="switchTab('p2pool')">P2Pool</div>
            </div>
            <div id="tab-monero" class="tab-content active">
                <div class="log-viewer" id="log-monero">Loading...</div>
            </div>
            <div id="tab-tari" class="tab-content">
                <div class="log-viewer" id="log-tari">Loading...</div>
            </div>
            <div id="tab-p2pool" class="tab-content">
                <div class="log-viewer" id="log-p2pool">Loading...</div>
            </div>
        </div>
    </div>
    <script>
        let hashChart = null;

        function formatHashrate(value) {{
            if (value >= 1000000000) return (value/1000000000).toFixed(2) + ' GH/s';
            if (value >= 1000000) return (value/1000000).toFixed(2) + ' MH/s';
            if (value >= 1000) return (value/1000).toFixed(2) + ' KH/s';
            return value.toFixed(2) + ' H/s';
        }}

        function initChart() {{
            const ctx = document.getElementById('hChart');
            hashChart = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: [],
                    datasets: [{{
                        label: 'Hashrate',
                        data: [],
                        borderColor: '#58a6ff',
                        tension: 0.3,
                        fill: true,
                        backgroundColor: 'rgba(88,166,255,0.1)'
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            grid: {{ color: '#30363d' }},
                            ticks: {{
                                callback: function(value) {{
                                    return formatHashrate(value);
                                }}
                            }}
                        }},
                        x: {{ display: false }}
                    }}
                }}
            }});
        }}

        async function updateChart() {{
            try {{
                const response = await fetch('/api/chart');
                const data = await response.json();

                // Update chart
                if (hashChart && data.history) {{
                    hashChart.data.labels = data.history.map(x => x.t);
                    hashChart.data.datasets[0].data = data.history.map(x => x.v);
                    hashChart.update('none'); // Update without animation for smoother real-time updates
                }}

                // Update top-right hashrate display
                const hashrateDisplay = document.getElementById('current-hashrate');
                if (hashrateDisplay && data.current_hashrate !== undefined) {{
                    hashrateDisplay.textContent = formatHashrate(data.current_hashrate);
                }}
            }} catch(e) {{
                console.error('Error updating chart:', e);
            }}
        }}

        // Initialize chart on page load
        window.addEventListener('load', () => {{
            initChart();
            updateChart(); // Initial update
            setInterval(updateChart, 5000); // Update every 5 seconds
        }});

        function toggleGroup(groupName) {{
            const rows = document.querySelectorAll(`tr.worker-detail[data-group="${{groupName}}"]`);
            const icon = document.getElementById(`icon-${{groupName}}`);
            rows.forEach(row => {{
                row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
            }});
            icon.classList.toggle('expanded');
        }}

        function switchTab(tabName) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(`tab-${{tabName}}`).classList.add('active');
            loadLogs(tabName);
        }}

        async function loadLogs(container) {{
            const logDiv = document.getElementById(`log-${{container}}`);
            logDiv.textContent = 'Loading...';
            try {{
                const response = await fetch(`/logs/${{container}}`);
                const text = await response.text();
                logDiv.textContent = text;
                logDiv.scrollTop = logDiv.scrollHeight;
            }} catch(e) {{
                logDiv.textContent = 'Error loading logs: ' + e.message;
            }}
        }}

        // Load monero logs on page load
        window.addEventListener('load', () => loadLogs('monero'));
    </script></body></html>
    """
    return web.Response(text=html, content_type='text/html')

async def handle_logs(request):
    """Handle log requests for different containers."""
    container = request.match_info.get('container', 'monerod')

    # Map friendly names to container names
    container_map = {
        'monero': 'monerod',
        'tari': 'tari',
        'p2pool': 'p2pool'
    }

    container_name = container_map.get(container, 'monerod')
    logs = get_container_logs(container_name, LOG_LINES)
    return web.Response(text=logs, content_type='text/plain')

async def handle_chart_data(request):
    """Return current hashrate history and total hashrate as JSON."""
    return web.json_response({
        'history': HASHRATE_HISTORY,
        'current_hashrate': LATEST_DATA.get('total_live_h15', 0) if LATEST_DATA else 0
    })

async def start_background_tasks(app):
    app['data_task'] = asyncio.create_task(update_data_loop())

if __name__ == "__main__":
    app = web.Application()
    app.add_routes([
        web.get('/', handle_get),
        web.get('/logs/{container}', handle_logs),
        web.get('/api/chart', handle_chart_data)
    ])
    app.on_startup.append(start_background_tasks)
    print("Dashboard running on port 8000 with Background Worker...", flush=True)
    web.run_app(app, host='0.0.0.0', port=8000)