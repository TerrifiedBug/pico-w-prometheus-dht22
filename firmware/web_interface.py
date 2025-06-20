"""
Web Interface Module for Pico W Prometheus DHT22 Sensor

This module handles all HTTP request routing and HTML generation,
keeping the main.py file focused on core sensor and OTA functionality.
"""

import time
import gc
from logger import log_info, log_warn, log_error, log_debug, get_logger
from device_config import (
    load_device_config,
    save_device_config,
    validate_config_input,
    get_config_for_metrics,
)
from config import SENSOR_CONFIG, WIFI_CONFIG, SERVER_CONFIG, METRICS_ENDPOINT


def get_shared_css():
    """Get shared CSS styles for consistent page design."""
    return """body{font-family:monospace;margin:20px;background:#f9f9f9}.container{max-width:1000px;background:white;padding:20px;border:1px solid #ddd;margin:0 auto}.nav{margin-bottom:20px}.nav a{color:#007bff;text-decoration:none;margin-right:20px}.nav a:hover{text-decoration:underline}.status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin:20px 0}.status-card{background:#f8f9fa;padding:15px;border:1px solid #dee2e6;border-radius:4px}.status-card h3{margin:0 0 10px 0;color:#495057}.status-ok{border-left:4px solid #28a745}.status-warn{border-left:4px solid #ffc107}.status-error{border-left:4px solid #dc3545}.status-info{border-left:4px solid #007bff}.metric-value{font-size:1.2em;font-weight:bold;color:#007bff}.metric-unit{font-size:0.9em;color:#6c757d}button{background:#007bff;color:white;border:none;cursor:pointer;padding:8px 16px;margin:5px}button:hover{background:#0056b3}button.success{background:#28a745}button.success:hover{background:#1e7e34}button.warning{background:#ffc107;color:#212529}button.warning:hover{background:#e0a800}button.danger{background:#dc3545}button.danger:hover{background:#c82333}.progress-bar{background:#e9ecef;height:20px;border-radius:4px;overflow:hidden;margin:10px 0}.progress-fill{background:#007bff;height:100%;transition:width 0.3s ease}.info-section{background:#e9ecef;padding:15px;margin:15px 0;border-left:4px solid #007bff}.endpoint-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:15px;margin:20px 0}.endpoint-card{background:#f8f9fa;padding:15px;border:1px solid #dee2e6;text-align:center}.endpoint-card a{color:#007bff;text-decoration:none;font-weight:bold}.endpoint-card a:hover{text-decoration:underline}.endpoint-desc{font-size:0.9em;color:#6c757d;margin-top:5px}"""


def handle_root_page(sensor_data, system_info, ota_updater):
    """Handle root page request with dashboard interface."""
    try:
        temp, hum = sensor_data
        sensor_status = "OK" if temp is not None else "FAIL"
        sensor_class = "status-ok" if temp is not None else "status-error"

        wifi_status, wifi_class, ip_address = system_info["wifi"]
        ota_status = "Enabled" if ota_updater else "Disabled"
        ota_class = "status-ok" if ota_updater else "status-warn"

        uptime_hours, uptime_minutes = system_info["uptime"]
        memory_mb = system_info["memory"]
        version = ota_updater.get_current_version() if ota_updater else "unknown"

        config = get_config_for_metrics()
        location, device_name = config["location"], config["device"]

        html = f"""<!DOCTYPE html><html><head><title>Pico W Sensor Dashboard</title><style>{get_shared_css()}</style><script>function refreshPage(){{window.location.reload()}}setInterval(refreshPage,30000);</script></head><body><div class="container"><h1>Pico W Sensor Dashboard</h1><div class="info-section"><strong>Device:</strong> {device_name} | <strong>Location:</strong> {location} | <strong>Version:</strong> {version}</div><div class="status-grid"><div class="status-card {sensor_class}"><h3>Sensor Status</h3><div class="metric-value">{sensor_status}</div>{"<div>" + str(temp) + "C | " + str(hum) + "%</div>" if temp is not None else "<div>Sensor Error</div>"}</div><div class="status-card {wifi_class}"><h3>Network</h3><div class="metric-value">{wifi_status}</div><div>IP: {ip_address}</div></div><div class="status-card {ota_class}"><h3>OTA Updates</h3><div class="metric-value">{ota_status}</div><div>Auto-update ready</div></div><div class="status-card status-info"><h3>System</h3><div class="metric-value">{uptime_hours:02d}:{uptime_minutes:02d}</div><div>{memory_mb}KB free</div></div></div><h2>Available Services</h2><div class="endpoint-grid"><div class="endpoint-card"><a href="/health">Health Check</a><div class="endpoint-desc">System status and diagnostics</div></div><div class="endpoint-card"><a href="/config">Configuration</a><div class="endpoint-desc">Device and OTA settings</div></div><div class="endpoint-card"><a href="/logs">System Logs</a><div class="endpoint-desc">Debug logs and monitoring</div></div><div class="endpoint-card"><a href="/update/status">OTA Status</a><div class="endpoint-desc">Update progress and control</div></div><div class="endpoint-card"><a href="/metrics">Metrics</a><div class="endpoint-desc">Prometheus metrics endpoint</div></div><div class="endpoint-card"><a href="/update">Update Now</a><div class="endpoint-desc">Trigger manual update</div></div></div><div style="margin-top:20px;text-align:center;color:#6c757d;font-size:0.9em">Page auto-refreshes every 30 seconds | Last updated: {time.time():.0f}</div></div></body></html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"
    except Exception as e:
        log_error(f"Root page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nDashboard error: {e}"


def handle_health_check(sensor_data, system_info, ota_updater, wlan, ssid):
    """Handle health check request with enhanced HTML interface."""
    try:
        temp, hum = sensor_data
        sensor_status = "OK" if temp is not None else "FAIL"
        sensor_class = "status-ok" if temp is not None else "status-error"

        ota_status = "Enabled" if ota_updater else "Disabled"
        ota_class = "status-ok" if ota_updater else "status-warn"

        wifi_status, wifi_class, ip_address = system_info["wifi"]
        uptime_days, uptime_hours, uptime_minutes = system_info["uptime_detailed"]
        free_memory, memory_mb, memory_class = system_info["memory_detailed"]

        version = ota_updater.get_current_version() if ota_updater else "unknown"
        config = get_config_for_metrics()
        location, device_name = config["location"], config["device"]

        overall_health = "HEALTHY"
        overall_class = "status-ok"
        if temp is None or not wlan.isconnected():
            overall_health = "DEGRADED"
            overall_class = "status-warn"
        if free_memory < 50000:
            overall_health = "CRITICAL"
            overall_class = "status-error"

        html = f"""<!DOCTYPE html><html><head><title>System Health Check</title><style>{get_shared_css()}</style><script>function refreshHealth(){{window.location.reload()}}function runSensorTest(){{refreshHealth()}}setInterval(refreshHealth,15000);</script></head><body><div class="container"><h1>System Health Check</h1><div class="nav"><a href="/">Back to Dashboard</a><a href="/config">Configuration</a><a href="/logs">System Logs</a><a href="/update/status">OTA Status</a></div><div class="info-section"><strong>Device:</strong> {device_name} | <strong>Location:</strong> {location} | <strong>Version:</strong> {version}</div><div class="status-grid"><div class="status-card {overall_class}"><h3>Overall Health</h3><div class="metric-value">{overall_health}</div><div>System status summary</div></div><div class="status-card {sensor_class}"><h3>DHT22 Sensor</h3><div class="metric-value">{sensor_status}</div>{"<div>" + str(temp) + "C | " + str(hum) + "%</div>" if temp is not None else "<div>Sensor Error</div>"}</div><div class="status-card {wifi_class}"><h3>Network</h3><div class="metric-value">{wifi_status}</div><div>IP: {ip_address}</div></div><div class="status-card {ota_class}"><h3>OTA System</h3><div class="metric-value">{ota_status}</div><div>Update system ready</div></div><div class="status-card status-info"><h3>Uptime</h3><div class="metric-value">{uptime_days}d {uptime_hours:02d}:{uptime_minutes:02d}</div><div>Days:Hours:Minutes</div></div><div class="status-card {memory_class}"><h3>Memory</h3><div class="metric-value">{memory_mb}KB</div><div>Free memory available</div></div></div><h2>Detailed Diagnostics</h2><div class="info-section"><h3>Sensor Readings</h3><strong>Temperature:</strong> {temp if temp is not None else "ERROR"}C<br><strong>Humidity:</strong> {hum if hum is not None else "ERROR"}%<br><strong>Sensor Pin:</strong> GPIO {SENSOR_CONFIG['pin']}<br><strong>Read Interval:</strong> {SENSOR_CONFIG['read_interval']}s</div><div class="info-section"><h3>Network Information</h3><strong>WiFi Status:</strong> {wifi_status}<br><strong>IP Address:</strong> {ip_address}<br><strong>Country Code:</strong> {WIFI_CONFIG['country_code']}<br><strong>SSID:</strong> {ssid if wlan.isconnected() else "Not connected"}</div><div class="info-section"><h3>System Resources</h3><strong>Free Memory:</strong> {free_memory:,} bytes ({memory_mb}KB)<br><strong>Uptime:</strong> {uptime_days} days, {uptime_hours} hours, {uptime_minutes} minutes<br><strong>Server Port:</strong> {SERVER_CONFIG['port']}</div><div class="info-section"><h3>Firmware Information</h3><strong>Version:</strong> {version}<br><strong>OTA Status:</strong> {ota_status}<br><strong>Metrics Endpoint:</strong> {METRICS_ENDPOINT}<br><strong>Device Config:</strong> {location}/{device_name}</div><div style="margin-top:20px"><button onclick="refreshHealth()">Refresh Health Check</button><button onclick="runSensorTest()" class="success">Test Sensor</button><a href="/logs"><button class="warning">View Logs</button></a><a href="/update/status"><button class="info">Check Updates</button></a></div><div style="margin-top:20px;text-align:center;color:#6c757d;font-size:0.9em">Health check auto-refreshes every 15 seconds | Last check: {time.time():.0f}</div></div></body></html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"
    except Exception as e:
        log_error(f"Health check failed: {e}", "SYSTEM")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nHealth check failed: {e}"


def handle_config_page():
    """Handle configuration page request."""
    try:
        config = load_device_config()
        device_config = config.get("device", {})
        ota_config = config.get("ota", {})

        location = device_config.get("location", "default-location")
        device_name = device_config.get("name", "default-device")
        description = device_config.get("description", "")
        last_updated = config.get("last_updated", "Never")

        ota_enabled = ota_config.get("enabled", True)
        auto_update = ota_config.get("auto_update", True)
        update_interval = ota_config.get("update_interval", 1.0)
        github_repo = ota_config.get("github_repo", {})
        repo_owner = github_repo.get("owner", "TerrifiedBug")
        repo_name = github_repo.get("name", "pico-w-prometheus-dht22")
        branch = github_repo.get("branch", "main")

        html = f"""<!DOCTYPE html><html><head><title>Device Configuration</title><style>body{{font-family:monospace;margin:40px;background:#f9f9f9}}.container{{max-width:800px;background:white;padding:30px;border:1px solid #ddd}}.tabs{{display:flex;margin-bottom:20px;border-bottom:2px solid #ddd}}.tab{{padding:10px 20px;cursor:pointer;background:#f0f0f0;border:1px solid #ddd;margin-right:5px}}.tab.active{{background:#007bff;color:white}}.tab-content{{display:none}}.tab-content.active{{display:block}}.form-group{{margin:15px 0}}.form-row{{display:flex;gap:15px}}.form-row .form-group{{flex:1}}label{{display:block;margin-bottom:5px;font-weight:bold}}input,textarea,select{{width:100%;padding:8px;font-family:monospace;border:1px solid #ccc;box-sizing:border-box}}input[type="checkbox"]{{width:auto}}button{{padding:12px 24px;margin-top:20px;background:#007bff;color:white;border:none;cursor:pointer}}button:hover{{background:#0056b3}}.current-config{{background:#e9ecef;padding:15px;margin-bottom:20px;border-left:4px solid #007bff}}.nav{{margin-bottom:20px}}.nav a{{color:#007bff;text-decoration:none;margin-right:20px}}.nav a:hover{{text-decoration:underline}}.note{{margin-top:20px;padding:15px;background:#fff3cd;border:1px solid #ffeaa7}}</style><script>function showTab(tabName){{var contents=document.getElementsByClassName('tab-content');for(var i=0;i<contents.length;i++){{contents[i].classList.remove('active')}}var tabs=document.getElementsByClassName('tab');for(var i=0;i<tabs.length;i++){{tabs[i].classList.remove('active')}}document.getElementById(tabName+'-content').classList.add('active');document.getElementById(tabName+'-tab').classList.add('active')}}</script></head><body><div class="container"><h1>Device Configuration</h1><div class="nav"><a href="/">< Back to Main Menu</a><a href="/health">Health Check</a><a href="/metrics">View Metrics</a><a href="/logs">System Logs</a><a href="/update/status">OTA Status</a></div><div class="current-config"><h3>Current Configuration:</h3><strong>Location:</strong> {location} | <strong>Device:</strong> {device_name}<br><strong>Description:</strong> {description if description else "(none)"}<br><strong>OTA:</strong> {"Enabled" if ota_enabled else "Disabled"} | <strong>Auto Update:</strong> {"Yes" if auto_update else "No"}<br><strong>Repository:</strong> {repo_owner}/{repo_name} ({branch}) | <strong>Interval:</strong> {update_interval}h<br><strong>Last Updated:</strong> {last_updated}</div><div class="tabs"><div class="tab active" id="device-tab" onclick="showTab('device')">Device Settings</div><div class="tab" id="ota-tab" onclick="showTab('ota')">OTA Settings</div></div><form method="POST"><div class="tab-content active" id="device-content"><h3>Device Settings</h3><div class="form-group"><label for="location">Location:</label><input type="text" id="location" name="location" value="{location}" placeholder="e.g., bedroom, kitchen, living-room"></div><div class="form-group"><label for="device">Device Name:</label><input type="text" id="device" name="device" value="{device_name}" placeholder="e.g., sensor-01, temp-sensor"></div><div class="form-group"><label for="description">Description (optional):</label><textarea id="description" name="description" rows="3" placeholder="Optional description of this sensor">{description}</textarea></div></div><div class="tab-content" id="ota-content"><h3>OTA Update Settings</h3><div class="form-group"><label><input type="checkbox" name="ota_enabled" {"checked" if ota_enabled else ""}> Enable OTA Updates</label></div><div class="form-group"><label><input type="checkbox" name="auto_update" {"checked" if auto_update else ""}> Enable Automatic Updates</label></div><div class="form-group"><label for="update_interval">Update Check Interval (hours):</label><input type="number" id="update_interval" name="update_interval" value="{update_interval}" min="0.5" max="168" step="0.5"></div><div class="form-row"><div class="form-group"><label for="repo_owner">GitHub Repository Owner:</label><input type="text" id="repo_owner" name="repo_owner" value="{repo_owner}"></div><div class="form-group"><label for="repo_name">Repository Name:</label><input type="text" id="repo_name" name="repo_name" value="{repo_name}"></div></div><div class="form-group"><label for="branch">Branch:</label><select id="branch" name="branch"><option value="main" {"selected" if branch == "main" else ""}>main (stable releases)</option><option value="dev" {"selected" if branch == "dev" else ""}>dev (development releases)</option></select></div></div><button type="submit">Save Configuration</button></form><div class="note"><strong>Note:</strong> Device settings take effect immediately. OTA settings will be applied on next update check or restart.</div></div></body></html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"
    except Exception as e:
        log_error(f"Configuration page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nConfiguration page error: {e}"


def handle_update_status(ota_updater, pending_update):
    """Handle update status request with enhanced HTML interface."""
    if not ota_updater:
        return "HTTP/1.0 503 Service Unavailable\r\nContent-Type: text/plain\r\n\r\nOTA disabled"

    try:
        status_info = ota_updater.get_update_status()
        current_version = status_info['current_version']

        if pending_update["scheduled"]:
            time_remaining = max(0, int(pending_update["start_time"] - time.time()))
            target_version = pending_update["version"]
            update_status = pending_update["status"]
            progress = pending_update["progress"]
            message = pending_update["message"]

            if time_remaining > 0:
                status_text = "WAITING FOR SCHEDULED TIME"
                status_class = "status-warn"
                progress_width = max(10, 100 - (time_remaining * 10))
            elif update_status == "downloading":
                status_text = "DOWNLOADING UPDATE FILES"
                status_class = "status-info"
                progress_width = progress
            elif update_status == "applying":
                status_text = "APPLYING UPDATE"
                status_class = "status-info"
                progress_width = progress
            elif update_status == "restarting":
                status_text = "RESTARTING DEVICE"
                status_class = "status-ok"
                progress_width = 100
            elif update_status == "failed":
                status_text = "UPDATE FAILED"
                status_class = "status-error"
                progress_width = 0
            else:
                status_text = "UPDATE STARTING NOW!"
                status_class = "status-info"
                progress_width = 10

            time_display = str(time_remaining) + "s" if time_remaining > 0 else "ACTIVE"

            html = f"""<!DOCTYPE html><html><head><title>OTA Update Status</title><style>{get_shared_css()}</style><script>setInterval(function(){{window.location.reload()}},2000);</script></head><body><div class="container"><h1>OTA Update in Progress</h1><div class="nav"><a href="/">Back to Dashboard</a><a href="/health">Health Check</a><a href="/logs">System Logs</a></div><div class="status-grid"><div class="status-card {status_class}"><h3>Update Status</h3><div class="metric-value">{status_text}</div><div>Time Remaining: {time_display}</div></div><div class="status-card status-info"><h3>Progress</h3><div class="metric-value">{progress_width}%</div><div class="progress-bar"><div class="progress-fill" style="width:{progress_width}%"></div></div></div><div class="status-card status-info"><h3>Version Info</h3><div class="metric-value">{current_version} > {target_version}</div><div>Repository: {status_info['repo']}</div></div></div><h2>Update Process</h2><div class="info-section"><h3>Current Step: {message}</h3><div style="margin-top:15px"><div>{"[X]" if True else "[ ]"} Update scheduled</div><div>{"[X]" if time_remaining <= 0 else "[ ]"} Waiting for start time</div><div>{"[X]" if update_status in ["downloading", "applying", "restarting"] else "[ ]"} Download update files</div><div>{"[X]" if update_status in ["applying", "restarting"] else "[ ]"} Apply update and backup</div><div>{"[X]" if update_status == "restarting" else "[ ]"} Device restart</div></div></div><div class="info-section"><h3>Important Information</h3><strong>When device restarts, this page will timeout and stop responding.</strong><br>This is NORMAL behavior! Wait 60-90 seconds, then visit /health to verify update.<br><br><strong>Do not power off the device during update!</strong></div><div style="margin-top:20px;text-align:center;color:#6c757d;font-size:0.9em">Page auto-refreshes every 2 seconds | Last updated: {time.time():.0f}</div></div></body></html>"""
            return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"
        else:
            ota_status_class = "status-ok" if status_info['ota_enabled'] else "status-warn"
            ota_enabled_text = "Enabled" if status_info['ota_enabled'] else "Disabled"
            auto_update_class = "status-ok" if status_info['auto_check'] else "status-warn"
            auto_update_text = "Enabled" if status_info['auto_check'] else "Disabled"

            html = f"""<!DOCTYPE html><html><head><title>OTA System Status</title><style>{get_shared_css()}</style><script>function checkForUpdates(){{window.location.href='/update'}}function refreshStatus(){{window.location.reload()}}</script></head><body><div class="container"><h1>OTA System Status</h1><div class="nav"><a href="/">Back to Dashboard</a><a href="/health">Health Check</a><a href="/config">Configuration</a><a href="/logs">System Logs</a></div><div class="status-grid"><div class="status-card status-ok"><h3>System Status</h3><div class="metric-value">READY</div><div>No pending updates</div></div><div class="status-card status-info"><h3>Current Version</h3><div class="metric-value">{current_version}</div><div>Installed firmware version</div></div><div class="status-card {ota_status_class}"><h3>OTA Status</h3><div class="metric-value">{ota_enabled_text}</div><div>Update system status</div></div><div class="status-card {auto_update_class}"><h3>Auto Updates</h3><div class="metric-value">{auto_update_text}</div><div>Automatic update checking</div></div></div><h2>System Information</h2><div class="info-section"><h3>Repository Configuration</h3><strong>Repository:</strong> {status_info['repo']}<br><strong>Branch:</strong> {status_info['branch']}<br><strong>Update Files:</strong> {', '.join(status_info['update_files']) if status_info['update_files'] else 'Auto-discovered'}</div><div class="info-section"><h3>Update Settings</h3><strong>OTA Enabled:</strong> {"Yes" if status_info['ota_enabled'] else "No"}<br><strong>Auto Check:</strong> {"Yes" if status_info['auto_check'] else "No"}<br><strong>Current Version:</strong> {current_version}</div><h2>Available Actions</h2><div style="margin-top:20px"><button onclick="checkForUpdates()" class="success">Check for Updates</button><button onclick="refreshStatus()">Refresh Status</button><a href="/health"><button class="info">System Health</button></a><a href="/config"><button class="warning">OTA Settings</button></a></div><div style="margin-top:20px;text-align:center;color:#6c757d;font-size:0.9em">System ready for OTA updates | Last checked: {time.time():.0f}</div></div></body></html>"""
            return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"
    except Exception as e:
        log_error(f"Status error: {e}", "OTA")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nStatus error: {e}"


def handle_logs_page(request):
    """Handle logs page request with filtering and web interface."""
    try:
        request_str = request.decode('utf-8')
        query_params = {}

        if '?' in request_str:
            query_string = request_str.split('?')[1].split(' ')[0]
            for param in query_string.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    query_params[key] = value

        level_filter = query_params.get('level', 'ALL')
        category_filter = query_params.get('category', 'ALL')
        action = query_params.get('action', '')

        if action == 'clear':
            logger = get_logger()
            logger.clear_logs()
            log_info("Logs cleared via web interface", "SYSTEM")
            return "HTTP/1.0 302 Found\r\nLocation: /logs\r\n\r\n"

        logger = get_logger()
        stats = logger.get_statistics()
        logs = logger.get_logs(level_filter, category_filter, last_n=100)

        log_lines = []
        for log in logs:
            timestamp_str = f"+{log['t']}s"
            line = f"[{timestamp_str:>6}] {log['l']:5} {log['c']:7}: {log['m']}"
            log_lines.append(line)

        logs_text = "\n".join(log_lines) if log_lines else "No logs found matching criteria."

        html = f"""<!DOCTYPE html><html><head><title>System Logs</title><style>body{{font-family:monospace;margin:20px;background:#f9f9f9}}.container{{max-width:1200px;background:white;padding:20px;border:1px solid #ddd}}.controls{{background:#e9ecef;padding:15px;margin-bottom:20px;border-left:4px solid #007bff}}.controls select,.controls button{{margin:5px;padding:8px;font-family:monospace}}.stats{{background:#f8f9fa;padding:10px;margin-bottom:15px;border:1px solid #dee2e6}}.logs{{background:#000;color:#0f0;padding:15px;font-family:'Courier New',monospace;font-size:12px;height:500px;overflow-y:auto;white-space:pre-wrap}}.nav{{margin-bottom:20px}}.nav a{{color:#007bff;text-decoration:none;margin-right:20px}}.nav a:hover{{text-decoration:underline}}button{{background:#007bff;color:white;border:none;cursor:pointer;padding:8px 16px}}button:hover{{background:#0056b3}}button.danger{{background:#dc3545}}button.danger:hover{{background:#c82333}}.auto-refresh{{margin-left:10px}}</style><script>function filterLogs(){{var level=document.getElementById('level').value;var category=document.getElementById('category').value;var url='/logs?level='+level+'&category='+category;window.location.href=url}}function clearLogs(){{if(confirm('Are you sure you want to clear all logs?')){{window.location.href='/logs?action=clear'}}}}function refreshLogs(){{window.location.reload()}}setInterval(function(){{if(document.getElementById('autoRefresh').checked){{refreshLogs()}}}},10000);</script></head><body><div class="container"><h1>System Logs</h1><div class="nav"><a href="/">< Back to Main Menu</a><a href="/health">Health Check</a><a href="/config">Configuration</a><a href="/update/status">OTA Status</a></div><div class="stats"><strong>Log Statistics:</strong> Entries: {stats['total_entries']}/{stats['max_entries']} | Memory: {stats['memory_usage_kb']}KB/{stats['max_memory_kb']}KB | Uptime: {stats['uptime_seconds']}s | Errors: {stats['logs_by_level']['ERROR']} | Warnings: {stats['logs_by_level']['WARN']}</div><div class="controls"><label>Level:</label><select id="level" onchange="filterLogs()"><option value="ALL" {"selected" if level_filter == "ALL" else ""}>ALL</option><option value="ERROR" {"selected" if level_filter == "ERROR" else ""}>ERROR</option><option value="WARN" {"selected" if level_filter == "WARN" else ""}>WARN</option><option value="INFO" {"selected" if level_filter == "INFO" else ""}>INFO</option><option value="DEBUG" {"selected" if level_filter == "DEBUG" else ""}>DEBUG</option></select><label>Category:</label><select id="category" onchange="filterLogs()"><option value="ALL" {"selected" if category_filter == "ALL" else ""}>ALL</option><option value="SYSTEM" {"selected" if category_filter == "SYSTEM" else ""}>SYSTEM</option><option value="OTA" {"selected" if category_filter == "OTA" else ""}>OTA</option><option value="SENSOR" {"selected" if category_filter == "SENSOR" else ""}>SENSOR</option><option value="CONFIG" {"selected" if category_filter == "CONFIG" else ""}>CONFIG</option><option value="NETWORK" {"selected" if category_filter == "NETWORK" else ""}>NETWORK</option><option value="HTTP" {"selected" if category_filter == "HTTP" else ""}>HTTP</option></select><button onclick="refreshLogs()">Refresh</button><button class="danger" onclick="clearLogs()">Clear Logs</button><label class="auto-refresh"><input type="checkbox" id="autoRefresh"> Auto-refresh (10s)</label></div><div class="logs">{logs_text}</div><div style="margin-top:15px;font-size:12px;color:#666">Showing last 100 entries. Logs are stored in memory only and will be lost on restart.</div></div></body></html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"
    except Exception as e:
        log_error(f"Logs page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nLogs page error: {e}"


def parse_form_data(request):
    """Parse form data from HTTP POST request."""
    try:
        request_str = request.decode('utf-8')
        lines = request_str.split('\r\n')

        form_data_line = ""
        found_empty = False
        for line in lines:
            if found_empty and line:
                form_data_line = line
                break
            if line == "":
                found_empty = True

        if not form_data_line:
            return {}

        form_data = {}
        pairs = form_data_line.split('&')
        for pair in pairs:
            if '=' in pair:
                key, value = pair.split('=', 1)
                key = key.replace('+', ' ')
                value = value.replace('+', ' ')
                # Basic URL decoding
                value = value.replace('%20', ' ').replace('%21', '!').replace('%22', '"')
                value = value.replace('%23', '#').replace('%24', '$').replace('%25', '%')
                value = value.replace('%26', '&').replace('%27', "'").replace('%28', '(')
                value = value.replace('%29', ')').replace('%2A', '*').replace('%2B', '+')
                value = value.replace('%2C', ',').replace('%2D', '-').replace('%2E', '.')
                value = value.replace('%2F', '/')
                form_data[key] = value

        return form_data
    except Exception as e:
        log_error(f"Error parsing form data: {e}", "HTTP")
        return {}


def handle_config_update(request):
    """Handle configuration update from POST request."""
    try:
        form_data = parse_form_data(request)
        log_info(f"Config update received: {list(form_data.keys())}", "CONFIG")

        config = validate_config_input(form_data)

        if save_device_config(config):
            log_info(f"Configuration updated: {config['device']['location']}/{config['device']['name']}", "CONFIG")
            return "HTTP/1.0 302 Found\r\nLocation: /config\r\n\r\n"
        else:
            log_error("Failed to save configuration", "CONFIG")
            return "HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nFailed to save configuration"
    except Exception as e:
        log_error(f"Configuration update failed: {e}", "CONFIG")
        return f"HTTP/1.0 400 Bad Request\r\nContent-Type: text/plain\r\n\r\nConfiguration update failed: {e}"
