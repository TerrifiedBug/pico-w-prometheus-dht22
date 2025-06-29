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


def unquote_plus(string):
    """MicroPython-compatible URL decoding function."""
    # Replace + with spaces
    string = string.replace('+', ' ')

    # Basic URL decoding for common characters
    replacements = {
        '%20': ' ', '%21': '!', '%22': '"', '%23': '#', '%24': '$', '%25': '%',
        '%26': '&', '%27': "'", '%28': '(', '%29': ')', '%2A': '*', '%2B': '+',
        '%2C': ',', '%2D': '-', '%2E': '.', '%2F': '/', '%3A': ':', '%3B': ';',
        '%3C': '<', '%3D': '=', '%3E': '>', '%3F': '?', '%40': '@', '%5B': '[',
        '%5C': '\\', '%5D': ']', '%5E': '^', '%5F': '_', '%60': '`', '%7B': '{',
        '%7C': '|', '%7D': '}', '%7E': '~'
    }

    for encoded, decoded in replacements.items():
        string = string.replace(encoded, decoded)

    return string


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


def handle_health_check(sensor_data, system_info, ota_updater, wlan, ssid, request_str=""):
    """Handle health check with minimal HTML and clickable links."""
    try:
        temp, hum = sensor_data
        wifi_status, _, ip_address = system_info["wifi"]
        uptime_days, uptime_hours, uptime_minutes = system_info["uptime_detailed"]
        free_memory, memory_mb, _ = system_info["memory_detailed"]

        version = ota_updater.get_current_version() if ota_updater else "unknown"
        config = get_config_for_metrics()
        location, device_name = config["location"], config["device"]

        # Minimal HTML health report with clickable links
        health_html = f"""<!DOCTYPE html><html><head><title>Health Check</title></head><body>
<h1>PICO W HEALTH CHECK</h1>

<h2>Device Information</h2>
<p><strong>Device:</strong> {device_name}<br>
<strong>Location:</strong> {location}<br>
<strong>Version:</strong> {version}</p>

<h2>Sensor Status</h2>
<p><strong>Status:</strong> {"OK" if temp is not None else "FAIL"}<br>
<strong>Temperature:</strong> {temp if temp is not None else "ERROR"}°C<br>
<strong>Humidity:</strong> {hum if hum is not None else "ERROR"}%<br>
<strong>Sensor Pin:</strong> GPIO {SENSOR_CONFIG['pin']}</p>

<h2>Network Status</h2>
<p><strong>Network:</strong> {wifi_status}<br>
<strong>IP Address:</strong> {ip_address}<br>
<strong>SSID:</strong> {ssid if wlan.isconnected() else "Not connected"}</p>

<h2>System Resources</h2>
<p><strong>Uptime:</strong> {uptime_days}d {uptime_hours:02d}:{uptime_minutes:02d}<br>
<strong>Free Memory:</strong> {free_memory:,} bytes ({memory_mb}KB)<br>
<strong>OTA Status:</strong> {"Enabled" if ota_updater else "Disabled"}</p>

<h2>Links</h2>
<p><a href="/">Dashboard</a> | <a href="/config">Config</a> | <a href="/logs">Logs</a> | <a href="/update">Update</a> | <a href="/metrics">Metrics</a></p>
</body></html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{health_html}"
    except Exception as e:
        log_error(f"Health check failed: {e}", "SYSTEM")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n<h1>Health Check Failed</h1><p>Error: {e}</p><p><a href='/'>Return home</a></p>"


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
    MAX_KEY_LEN = 32
    MAX_VALUE_LEN = 128
    try:
        request_str = request.decode("utf-8")
        body_start = request_str.find("\r\n\r\n")
        if body_start == -1:
            return {}
        form_body = request_str[body_start + 4 :]
        if not form_body:
            return {}

        form_data = {}
        pairs = form_body.split("&")
        for pair in pairs:
            if "=" in pair:
                key, value = pair.split("=", 1)
                key = unquote_plus(key)[:MAX_KEY_LEN]
                value = unquote_plus(value)[:MAX_VALUE_LEN]
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
