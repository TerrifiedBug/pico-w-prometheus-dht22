"""
Minimal Web Interface for Pico W Prometheus DHT22 Sensor
Ultra-lightweight implementation to maximize memory for OTA updates.
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


def handle_root_page(sensor_data, system_info, ota_updater):
    """Handle root page with minimal plain text dashboard."""
    try:
        temp, hum = sensor_data
        wifi_status, _, ip_address = system_info["wifi"]
        uptime_hours, uptime_minutes = system_info["uptime"]
        memory_mb = system_info["memory"]
        version = ota_updater.get_current_version() if ota_updater else "unknown"

        config = get_config_for_metrics()
        location, device_name = config["location"], config["device"]

        # Ultra-minimal HTML
        html = f"""<!DOCTYPE html><html><head><title>Pico W Sensor</title></head><body>
<h1>Pico W Sensor Dashboard</h1>
<p><strong>Device:</strong> {device_name} | <strong>Location:</strong> {location} | <strong>Version:</strong> {version}</p>
<h2>Status</h2>
<p>Sensor: {"OK" if temp is not None else "FAIL"} | Temp: {temp if temp else "N/A"}C | Humidity: {hum if hum else "N/A"}%</p>
<p>Network: {wifi_status} | IP: {ip_address}</p>
<p>Uptime: {uptime_hours:02d}:{uptime_minutes:02d} | Memory: {memory_mb}KB</p>
<h2>Links</h2>
<p><a href="/health">Health</a> | <a href="/config">Config</a> | <a href="/logs">Logs</a> | <a href="/update">Update</a> | <a href="/metrics">Metrics</a></p>
</body></html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"
    except Exception as e:
        log_error(f"Root page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nError: {e}"


def handle_health_check(sensor_data, system_info, ota_updater, wlan, ssid):
    """Handle health check with plain text response."""
    try:
        temp, hum = sensor_data
        wifi_status, _, ip_address = system_info["wifi"]
        uptime_days, uptime_hours, uptime_minutes = system_info["uptime_detailed"]
        free_memory, memory_mb, _ = system_info["memory_detailed"]

        version = ota_updater.get_current_version() if ota_updater else "unknown"
        config = get_config_for_metrics()
        location, device_name = config["location"], config["device"]

        # Plain text health report
        health_text = f"""Pico W Health Check
==================

Device: {device_name}
Location: {location}
Version: {version}

Sensor Status: {"OK" if temp is not None else "FAIL"}
Temperature: {temp if temp is not None else "ERROR"}C
Humidity: {hum if hum is not None else "ERROR"}%
Sensor Pin: GPIO {SENSOR_CONFIG['pin']}

Network: {wifi_status}
IP Address: {ip_address}
SSID: {ssid if wlan.isconnected() else "Not connected"}

System Uptime: {uptime_days}d {uptime_hours:02d}:{uptime_minutes:02d}
Free Memory: {free_memory:,} bytes ({memory_mb}KB)
OTA Status: {"Enabled" if ota_updater else "Disabled"}

Links: /config /logs /update /metrics
"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n{health_text}"
    except Exception as e:
        log_error(f"Health check failed: {e}", "SYSTEM")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nHealth check failed: {e}"


def handle_config_page():
    """Handle configuration page with minimal HTML form."""
    try:
        config = load_device_config()
        device_config = config.get("device", {})
        ota_config = config.get("ota", {})

        location = device_config.get("location", "default-location")
        device_name = device_config.get("name", "default-device")
        description = device_config.get("description", "")

        ota_enabled = ota_config.get("enabled", True)
        auto_update = ota_config.get("auto_update", True)
        update_interval = ota_config.get("update_interval", 1.0)
        github_repo = ota_config.get("github_repo", {})
        repo_owner = github_repo.get("owner", "TerrifiedBug")
        repo_name = github_repo.get("name", "pico-w-prometheus-dht22")
        branch = github_repo.get("branch", "main")

        # Minimal HTML form
        html = f"""<!DOCTYPE html><html><head><title>Device Config</title></head><body>
<h1>Device Configuration</h1>
<p><a href="/">Back</a> | <a href="/health">Health</a> | <a href="/logs">Logs</a></p>

<h2>Current Settings</h2>
<p>Device: {device_name} | Location: {location}</p>
<p>OTA: {"Enabled" if ota_enabled else "Disabled"} | Auto: {"Yes" if auto_update else "No"}</p>
<p>Repo: {repo_owner}/{repo_name} ({branch})</p>

<h2>Update Configuration</h2>
<form method="POST">
<p>Location: <input type="text" name="location" value="{location}" size="20"></p>
<p>Device Name: <input type="text" name="device" value="{device_name}" size="20"></p>
<p>Description: <input type="text" name="description" value="{description}" size="30"></p>
<p><input type="checkbox" name="ota_enabled" {"checked" if ota_enabled else ""}> Enable OTA Updates</p>
<p><input type="checkbox" name="auto_update" {"checked" if auto_update else ""}> Auto Updates</p>
<p>Update Interval (hours): <input type="number" name="update_interval" value="{update_interval}" min="0.5" max="168" step="0.5" size="5"></p>
<p>Repo Owner: <input type="text" name="repo_owner" value="{repo_owner}" size="15"></p>
<p>Repo Name: <input type="text" name="repo_name" value="{repo_name}" size="25"></p>
<p>Branch: <select name="branch">
<option value="main" {"selected" if branch == "main" else ""}>main</option>
<option value="dev" {"selected" if branch == "dev" else ""}>dev</option>
</select></p>
<p><input type="submit" value="Save Configuration"></p>
</form>
</body></html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"
    except Exception as e:
        log_error(f"Config page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nConfig error: {e}"


def handle_update_status(ota_updater, pending_update):
    """Handle update status with plain text response."""
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

            status_text = f"""OTA Update Status
================

Current Version: {current_version}
Target Version: {target_version}
Status: {update_status.upper()}
Progress: {progress}%
Message: {message}
Time Remaining: {time_remaining}s

Repository: {status_info['repo']}

IMPORTANT: Device will restart during update!
Wait 60-90 seconds after restart, then check /health
"""
            return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nRefresh: 2\r\n\r\n{status_text}"
        else:
            status_text = f"""OTA System Status
================

Current Version: {current_version}
OTA Enabled: {"Yes" if status_info['ota_enabled'] else "No"}
Auto Updates: {"Yes" if status_info['auto_check'] else "No"}
Repository: {status_info['repo']}
Branch: {status_info['branch']}

Status: READY (No pending updates)

Actions: /update (check for updates)
"""
            return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n{status_text}"
    except Exception as e:
        log_error(f"Status error: {e}", "OTA")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nStatus error: {e}"


def handle_logs_page(request):
    """Handle logs page with plain text output."""
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
        logs = logger.get_logs(level_filter, category_filter, last_n=50)

        log_lines = []
        for log in logs:
            timestamp_str = f"+{log['t']}s"
            line = f"[{timestamp_str:>6}] {log['l']:5} {log['c']:7}: {log['m']}"
            log_lines.append(line)

        logs_text = "\n".join(log_lines) if log_lines else "No logs found."

        response_text = f"""System Logs
===========

Stats: {stats['total_entries']} entries | {stats['memory_usage_kb']}KB | Errors: {stats['logs_by_level']['ERROR']}

Filter: level={level_filter} category={category_filter}
Links: /logs?level=ERROR /logs?level=OTA /logs?action=clear

{logs_text}

Showing last 50 entries. Logs cleared on restart.
"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n{response_text}"
    except Exception as e:
        log_error(f"Logs page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nLogs error: {e}"


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
        log_info(f"Config update: {list(form_data.keys())}", "CONFIG")

        config = validate_config_input(form_data)

        if save_device_config(config):
            log_info(f"Config updated: {config['device']['location']}/{config['device']['name']}", "CONFIG")
            return "HTTP/1.0 302 Found\r\nLocation: /config\r\n\r\n"
        else:
            log_error("Failed to save configuration", "CONFIG")
            return "HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nFailed to save config"
    except Exception as e:
        log_error(f"Config update failed: {e}", "CONFIG")
        return f"HTTP/1.0 400 Bad Request\r\nContent-Type: text/plain\r\n\r\nConfig update failed: {e}"
