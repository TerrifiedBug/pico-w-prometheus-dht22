"""
Pico W Prometheus DHT22 Sensor Server

A MicroPython-based HTTP server for the Raspberry Pi Pico W that exposes
DHT22 sensor readings (temperature and humidity) as Prometheus-compatible metrics.

This module connects to WiFi, reads from a DHT22 sensor, and serves metrics
via an HTTP endpoint for Prometheus scraping.
"""

import socket
import time
from secrets import secrets

import dht
import network
import rp2
from machine import Pin

from config import (
    METRIC_NAMES,
    METRICS_ENDPOINT,
    OTA_CONFIG,
    SENSOR_CONFIG,
    SERVER_CONFIG,
    WIFI_CONFIG,
)
from device_config import (
    load_device_config,
    save_device_config,
    validate_config_input,
    get_config_for_metrics,
)
from logger import log_info, log_warn, log_error, log_debug, get_logger

# Record boot time using ticks for accurate uptime calculation
boot_ticks = time.ticks_ms()

# Global update queue for delayed updates with progress tracking
pending_update = {
    "scheduled": False,
    "version": None,
    "start_time": 0,
    "current_version": None,
    "status": "idle",  # idle, scheduled, downloading, applying, restarting, completed
    "progress": 0,
    "message": "Ready for updates"
}

# Wi-Fi Setup
ssid = secrets["ssid"]
password = secrets["pw"]
rp2.country(WIFI_CONFIG["country_code"])

def connect_wifi():
    """
    Connect to WiFi with improved error handling and retry logic.

    Returns:
        bool: True if connected successfully, False otherwise.
    """
    log_info("Connecting to Wi-Fi...", "NETWORK")
    wlan.connect(ssid, password)

    max_wait = 20  # Increased timeout
    while max_wait > 0:
        status = wlan.status()

        if status == 3:  # Connected
            ip = wlan.ifconfig()[0]
            log_info(f"WiFi connected, IP: {ip}", "NETWORK")
            return True
        elif status < 0:  # Error states (-1, -2, -3)
            log_warn(f"Connection failed with status {status}, retrying...", "NETWORK")
            wlan.disconnect()
            time.sleep(2)
            wlan.connect(ssid, password)
            max_wait = 20  # Reset timeout for retry
        else:
            log_debug(f"Connecting... (status: {status}, {max_wait}s remaining)", "NETWORK")

        max_wait -= 1
        time.sleep(1)

    # If we get here, connection failed
    log_error("WiFi connection timeout", "NETWORK")
    return False


wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# Connect with improved reliability
if not connect_wifi():
    log_error("Initial connection failed, trying once more...", "NETWORK")
    time.sleep(5)
    if not connect_wifi():
        log_error("Wi-Fi connection failed after retries", "NETWORK")
        raise RuntimeError("Wi-Fi connection failed after retries")

# DHT22 Sensor Setup
sensor = dht.DHT22(Pin(SENSOR_CONFIG["pin"]))
log_info(f"DHT22 sensor initialized on pin {SENSOR_CONFIG['pin']}", "SENSOR")

# OTA Updater Setup
ota_updater = None
if OTA_CONFIG["enabled"]:
    try:
        from ota_updater import GitHubOTAUpdater
        ota_updater = GitHubOTAUpdater()
        log_info("OTA updater initialized", "OTA")
    except Exception as e:
        log_error(f"Failed to initialize OTA updater: {e}", "OTA")


def read_dht22():
    """
    Read temperature and humidity from the DHT22 sensor.

    Returns:
        tuple: A tuple containing (temperature, humidity) as floats rounded to 2 decimal places,
               or (None, None) if the sensor reading fails.
    """
    try:
        sensor.measure()
        t = sensor.temperature()
        h = sensor.humidity()
        log_debug(f"Sensor reading: {t}°C, {h}%", "SENSOR")
        return round(t, 2), round(h, 2)
    except Exception as e:
        log_error(f"Sensor read failed: {e}", "SENSOR")
        return None, None


def format_metrics(temperature, humidity):
    """
    Format temperature, humidity, and system health as Prometheus metrics with dynamic labels.

    Args:
        temperature (float): Temperature reading in Celsius.
        humidity (float): Humidity reading as a percentage.

    Returns:
        str: Formatted Prometheus metrics string with HELP and TYPE comments and dynamic labels.
    """
    # Get device configuration for labels
    config = get_config_for_metrics()
    location = config["location"]
    device = config["device"]

    # Create label string for metrics
    labels = f'{{location="{location}",device="{device}"}}'

    # Basic sensor metrics with labels
    metrics = []

    # Temperature and humidity with dynamic labels
    metrics.extend([
        f"# HELP {METRIC_NAMES['temperature']} Temperature in Celsius",
        f"# TYPE {METRIC_NAMES['temperature']} gauge",
        f"{METRIC_NAMES['temperature']}{labels} {temperature}",
        f"# HELP {METRIC_NAMES['humidity']} Humidity in Percent",
        f"# TYPE {METRIC_NAMES['humidity']} gauge",
        f"{METRIC_NAMES['humidity']}{labels} {humidity}",
    ])

    # System health metrics with labels
    sensor_status = 1 if temperature is not None else 0
    ota_status = 1 if ota_updater else 0

    metrics.extend([
        "# HELP pico_sensor_status Sensor health status (1=OK, 0=FAIL)",
        "# TYPE pico_sensor_status gauge",
        f"pico_sensor_status{labels} {sensor_status}",
        "# HELP pico_ota_status OTA system status (1=enabled, 0=disabled)",
        "# TYPE pico_ota_status gauge",
        f"pico_ota_status{labels} {ota_status}",
    ])

    # Version information with labels
    if ota_updater:
        current_version = ota_updater.get_current_version()
        version_labels = f'{{location="{location}",device="{device}",version="{current_version}"}}'
        metrics.extend([
            "# HELP pico_version_info Current firmware version",
            "# TYPE pico_version_info gauge",
            f"pico_version_info{version_labels} 1",
        ])

    # System uptime (actual time since boot using ticks) with labels
    uptime_ms = time.ticks_diff(time.ticks_ms(), boot_ticks)

    # Handle potential negative values from tick wraparound
    if uptime_ms < 0:
        # If negative, likely due to tick counter wraparound (every ~12.4 days)
        # Calculate using the wraparound period (2^30 ms for MicroPython)
        uptime_ms = uptime_ms + (1 << 30)

    uptime_seconds = max(0, uptime_ms // 1000)  # Ensure non-negative
    metrics.extend([
        "# HELP pico_uptime_seconds Actual uptime in seconds since boot",
        "# TYPE pico_uptime_seconds counter",
        f"pico_uptime_seconds{labels} {uptime_seconds}",
    ])

    return "\n".join(metrics) + "\n"


def handle_update_request_delayed():
    """
    Handle OTA update request with delayed execution and redirect to status page.

    Returns:
        str: HTTP response for update request.
    """
    if not ota_updater:
        log_warn("OTA update requested but OTA not enabled", "OTA")
        return "HTTP/1.0 503 Service Unavailable\r\nContent-Type: text/plain\r\n\r\nOTA not enabled"

    try:
        log_info("Manual update requested", "OTA")

        # Check if update is already scheduled
        if pending_update["scheduled"]:
            log_info("Update already scheduled, redirecting to status", "OTA")
            return "HTTP/1.0 302 Found\r\nLocation: /update/status\r\n\r\n"

        # Check for available updates
        has_update, new_version, _ = ota_updater.check_for_updates()

        if not has_update:
            log_info("No updates available", "OTA")
            return "HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nNo updates available\n\nCurrent version is up to date."

        # Get current version for display
        current_version = ota_updater.get_current_version()

        # Schedule update for 10 seconds later
        pending_update["scheduled"] = True
        pending_update["version"] = new_version
        pending_update["current_version"] = current_version
        pending_update["start_time"] = time.time() + 10

        log_info(f"Update to {new_version} scheduled for 10 seconds", "OTA")

        # Return plain text response with redirect
        response_text = f"""Update Scheduled Successfully!
================================

Current Version: {current_version}
Target Version: {new_version}
Update will start in: 10 seconds

IMPORTANT: What happens during update:
1. Update begins automatically after 10 seconds
2. Status page will show progress briefly
3. Device WILL RESTART during update (this is normal!)
4. Web page will timeout when device restarts
5. Wait 60-90 seconds for update to complete
6. Device will come back online automatically
7. Visit /health to confirm new version

Visit /update/status to monitor initial progress.
"""
        return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nRefresh: 3; url=/update/status\r\n\r\n{response_text}"

    except Exception as e:
        log_error(f"Update request failed: {e}", "OTA")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nUpdate scheduling failed: {e}"


def perform_scheduled_update():
    """
    Perform the scheduled OTA update with progress tracking.
    """
    try:
        log_info(f"Starting scheduled update to version {pending_update['version']}", "OTA")

        # Update status: Starting download
        pending_update["status"] = "downloading"
        pending_update["progress"] = 25
        pending_update["message"] = "Downloading update files..."

        # Check for updates again (quick check)
        has_update, new_version, _ = ota_updater.check_for_updates()
        if not has_update:
            log_warn("No update available during scheduled update", "OTA")
            pending_update["scheduled"] = False
            pending_update["status"] = "idle"
            return

        # Update status: Downloading files
        log_info("Downloading update files...", "OTA")
        download_success = ota_updater.download_update(new_version)

        if not download_success:
            log_error("Download failed", "OTA")
            pending_update["status"] = "failed"
            pending_update["message"] = "Download failed"
            pending_update["scheduled"] = False
            return

        # Update status: Applying update
        pending_update["status"] = "applying"
        pending_update["progress"] = 75
        pending_update["message"] = "Applying update and backing up files..."
        log_info("Applying update...", "OTA")

        # Small delay to allow status page to show this step
        time.sleep(1)

        # Apply the update
        apply_success = ota_updater.apply_update(new_version)

        if apply_success:
            # Update status: About to restart
            pending_update["status"] = "restarting"
            pending_update["progress"] = 100
            pending_update["message"] = "Update complete, restarting device..."
            log_info("Update completed successfully, device will restart in 2 seconds", "OTA")

            # Brief delay to show final status
            time.sleep(2)

            # Device will restart here
            import machine
            machine.reset()
        else:
            log_error("Update application failed", "OTA")
            pending_update["status"] = "failed"
            pending_update["message"] = "Update application failed"
            pending_update["scheduled"] = False

    except Exception as e:
        log_error(f"Scheduled update failed: {e}", "OTA")
        pending_update["status"] = "failed"
        pending_update["message"] = f"Update error: {str(e)}"
        pending_update["scheduled"] = False


def handle_update_status():
    """
    Handle update status request with plain text interface.

    Returns:
        str: HTTP response with update status information.
    """
    if not ota_updater:
        return "HTTP/1.0 503 Service Unavailable\r\nContent-Type: text/plain\r\n\r\nOTA disabled"

    try:
        status_info = ota_updater.get_update_status()
        current_version = status_info['current_version']

        # Check if there's a pending update
        if pending_update["scheduled"]:
            time_remaining = max(0, int(pending_update["start_time"] - time.time()))
            target_version = pending_update["version"]
            update_status = pending_update["status"]
            progress = pending_update["progress"]
            message = pending_update["message"]

            # Determine status display based on current state
            if time_remaining > 0:
                status_text = "WAITING FOR SCHEDULED TIME"
                progress_width = max(10, 100 - (time_remaining * 10))
            elif update_status == "downloading":
                status_text = "DOWNLOADING UPDATE FILES"
                progress_width = progress
            elif update_status == "applying":
                status_text = "APPLYING UPDATE"
                progress_width = progress
            elif update_status == "restarting":
                status_text = "RESTARTING DEVICE"
                progress_width = 100
            elif update_status == "failed":
                status_text = "UPDATE FAILED"
                progress_width = 0
            else:
                status_text = "UPDATE STARTING NOW!"
                progress_width = 10

            # Return plain text status
            status_text_response = f"""OTA Update Status
=================

Status: {status_text}
Time Remaining: {time_remaining if time_remaining > 0 else "ACTIVE"}s
Progress: {progress_width}%

Current Version: {current_version}
Target Version: {target_version}
Repository: {status_info['repo']}

Update Process:
[X] Update scheduled
[{"X" if time_remaining <= 0 else "O"}] Waiting for start time
[{"X" if update_status in ["downloading", "applying", "restarting"] else "O"}] Download update files
[{"X" if update_status in ["applying", "restarting"] else "O"}] Apply update and backup
[{"X" if update_status == "restarting" else "O"}] Device restart

Current Step: {message}

IMPORTANT: When device restarts, this page will timeout and stop responding.
This is NORMAL behavior! Wait 60-90 seconds, then visit /health to verify update.
"""
            return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nRefresh: 2\r\n\r\n{status_text_response}"
        else:
            # No pending update - show normal status
            status_text_response = f"""OTA System Status
=================

Status: READY - No pending updates

Current Version: {current_version}
OTA Enabled: {"Yes" if status_info['ota_enabled'] else "No"}
Auto Check: {"Yes" if status_info['auto_check'] else "No"}
Repository: {status_info['repo']}
Branch: {status_info['branch']}
Update Files: {', '.join(status_info['update_files'])}

System ready for OTA updates.

Available Actions:
- Visit /update to check for updates
- Visit /health for system health check
- Visit / for main menu
"""
            return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n{status_text_response}"

    except Exception as e:
        log_error(f"Status error: {e}", "OTA")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nStatus error: {e}"


def handle_health_check():
    """
    Handle health check request.

    Returns:
        str: HTTP response for health check.
    """
    try:
        # Test sensor reading
        temp, hum = read_dht22()
        sensor_status = "OK" if temp is not None else "FAIL"

        # Check OTA status
        ota_status = "OK" if ota_updater else "DISABLED"

        # Get system information with proper tick wraparound handling
        uptime_ms = time.ticks_diff(time.ticks_ms(), boot_ticks)

        # Handle potential negative values from tick wraparound
        if uptime_ms < 0:
            # If negative, likely due to tick counter wraparound (every ~12.4 days)
            # Calculate using the wraparound period (2^30 ms for MicroPython)
            uptime_ms = uptime_ms + (1 << 30)

        uptime_seconds = max(0, uptime_ms // 1000)  # Ensure non-negative
        uptime_hours = uptime_seconds // 3600
        uptime_minutes = (uptime_seconds % 3600) // 60

        # WiFi information
        wifi_status = "Connected" if wlan.isconnected() else "Disconnected"
        ip_address = wlan.ifconfig()[0] if wlan.isconnected() else "N/A"

        # Memory information
        import gc
        gc.collect()
        free_memory = gc.mem_free()

        health_info = f"""System Health Check

Sensor Status: {sensor_status}
Temperature: {temp if temp is not None else "ERROR"}C
Humidity: {hum if hum is not None else "ERROR"}%

Network Status: {wifi_status}
IP Address: {ip_address}

OTA Status: {ota_status}
Version: {ota_updater.get_current_version() if ota_updater else "unknown"}

System Info:
Uptime: {uptime_hours:02d}:{uptime_minutes:02d}
Free Memory: {free_memory:,} bytes
"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n{health_info}"

    except Exception as e:
        log_error(f"Health check failed: {e}", "SYSTEM")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nHealth check failed: {e}"


def handle_config_page():
    """
    Handle configuration page request - show enhanced HTML form with device and OTA settings.

    Returns:
        str: HTTP response with HTML configuration form.
    """
    try:
        # Load current configuration
        config = load_device_config()
        device_config = config.get("device", {})
        ota_config = config.get("ota", {})

        location = device_config.get("location", "default-location")
        device_name = device_config.get("name", "default-device")
        description = device_config.get("description", "")
        last_updated = config.get("last_updated", "Never")

        # OTA settings
        ota_enabled = ota_config.get("enabled", True)
        auto_update = ota_config.get("auto_update", True)
        update_interval = ota_config.get("update_interval", 1.0)
        github_repo = ota_config.get("github_repo", {})
        repo_owner = github_repo.get("owner", "TerrifiedBug")
        repo_name = github_repo.get("name", "pico-w-prometheus-dht22")
        branch = github_repo.get("branch", "main")

        # Generate HTML form with tabs
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Device Configuration</title>
    <style>
        body {{ font-family: monospace; margin: 40px; background: #f9f9f9; }}
        .container {{ max-width: 800px; background: white; padding: 30px; border: 1px solid #ddd; }}
        .tabs {{ display: flex; margin-bottom: 20px; border-bottom: 2px solid #ddd; }}
        .tab {{ padding: 10px 20px; cursor: pointer; background: #f0f0f0; border: 1px solid #ddd; margin-right: 5px; }}
        .tab.active {{ background: #007bff; color: white; }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        .form-group {{ margin: 15px 0; }}
        .form-row {{ display: flex; gap: 15px; }}
        .form-row .form-group {{ flex: 1; }}
        label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
        input, textarea, select {{ width: 100%; padding: 8px; font-family: monospace; border: 1px solid #ccc; box-sizing: border-box; }}
        input[type="checkbox"] {{ width: auto; }}
        button {{ padding: 12px 24px; margin-top: 20px; background: #007bff; color: white; border: none; cursor: pointer; }}
        button:hover {{ background: #0056b3; }}
        .current-config {{ background: #e9ecef; padding: 15px; margin-bottom: 20px; border-left: 4px solid #007bff; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #007bff; text-decoration: none; margin-right: 20px; }}
        .nav a:hover {{ text-decoration: underline; }}
        .note {{ margin-top: 20px; padding: 15px; background: #fff3cd; border: 1px solid #ffeaa7; }}
    </style>
    <script>
        function showTab(tabName) {{
            // Hide all tab contents
            var contents = document.getElementsByClassName('tab-content');
            for (var i = 0; i < contents.length; i++) {{
                contents[i].classList.remove('active');
            }}

            // Remove active class from all tabs
            var tabs = document.getElementsByClassName('tab');
            for (var i = 0; i < tabs.length; i++) {{
                tabs[i].classList.remove('active');
            }}

            // Show selected tab content and mark tab as active
            document.getElementById(tabName + '-content').classList.add('active');
            document.getElementById(tabName + '-tab').classList.add('active');
        }}
    </script>
</head>
<body>
    <div class="container">
        <h1>Device Configuration</h1>

        <div class="nav">
            <a href="/">← Back to Main Menu</a>
            <a href="/health">Health Check</a>
            <a href="/metrics">View Metrics</a>
            <a href="/logs">System Logs</a>
            <a href="/update/status">OTA Status</a>
        </div>

        <div class="current-config">
            <h3>Current Configuration:</h3>
            <strong>Location:</strong> {location} | <strong>Device:</strong> {device_name}<br>
            <strong>Description:</strong> {description if description else "(none)"}<br>
            <strong>OTA:</strong> {"Enabled" if ota_enabled else "Disabled"} | <strong>Auto Update:</strong> {"Yes" if auto_update else "No"}<br>
            <strong>Repository:</strong> {repo_owner}/{repo_name} ({branch}) | <strong>Interval:</strong> {update_interval}h<br>
            <strong>Last Updated:</strong> {last_updated}
        </div>

        <div class="tabs">
            <div class="tab active" id="device-tab" onclick="showTab('device')">Device Settings</div>
            <div class="tab" id="ota-tab" onclick="showTab('ota')">OTA Settings</div>
        </div>

        <form method="POST">
            <!-- Device Settings Tab -->
            <div class="tab-content active" id="device-content">
                <h3>Device Settings</h3>
                <div class="form-group">
                    <label for="location">Location:</label>
                    <input type="text" id="location" name="location" value="{location}" placeholder="e.g., bedroom, kitchen, living-room">
                </div>

                <div class="form-group">
                    <label for="device">Device Name:</label>
                    <input type="text" id="device" name="device" value="{device_name}" placeholder="e.g., sensor-01, temp-sensor">
                </div>

                <div class="form-group">
                    <label for="description">Description (optional):</label>
                    <textarea id="description" name="description" rows="3" placeholder="Optional description of this sensor">{description}</textarea>
                </div>
            </div>

            <!-- OTA Settings Tab -->
            <div class="tab-content" id="ota-content">
                <h3>OTA Update Settings</h3>

                <div class="form-group">
                    <label>
                        <input type="checkbox" name="ota_enabled" {"checked" if ota_enabled else ""}> Enable OTA Updates
                    </label>
                </div>

                <div class="form-group">
                    <label>
                        <input type="checkbox" name="auto_update" {"checked" if auto_update else ""}> Enable Automatic Updates
                    </label>
                </div>

                <div class="form-group">
                    <label for="update_interval">Update Check Interval (hours):</label>
                    <input type="number" id="update_interval" name="update_interval" value="{update_interval}" min="0.5" max="168" step="0.5">
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label for="repo_owner">GitHub Repository Owner:</label>
                        <input type="text" id="repo_owner" name="repo_owner" value="{repo_owner}">
                    </div>
                    <div class="form-group">
                        <label for="repo_name">Repository Name:</label>
                        <input type="text" id="repo_name" name="repo_name" value="{repo_name}">
                    </div>
                </div>

                <div class="form-group">
                    <label for="branch">Branch:</label>
                    <select id="branch" name="branch">
                        <option value="main" {"selected" if branch == "main" else ""}>main (stable releases)</option>
                        <option value="dev" {"selected" if branch == "dev" else ""}>dev (development releases)</option>
                    </select>
                </div>
            </div>

            <button type="submit">Save Configuration</button>
        </form>

        <div class="note">
            <strong>Note:</strong> Device settings take effect immediately. OTA settings will be applied on next update check or restart.
        </div>
    </div>
</body>
</html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"

    except Exception as e:
        log_error(f"Configuration page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nConfiguration page error: {e}"


def parse_form_data(request):
    """
    Parse form data from HTTP POST request.

    Args:
        request (bytes): Raw HTTP request data

    Returns:
        dict: Parsed form data
    """
    try:
        # Decode request and split into lines
        request_str = request.decode('utf-8')
        lines = request_str.split('\r\n')

        # Find the form data (after empty line)
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

        # Parse URL-encoded form data
        form_data = {}
        pairs = form_data_line.split('&')
        for pair in pairs:
            if '=' in pair:
                key, value = pair.split('=', 1)
                # URL decode
                key = key.replace('+', ' ')
                value = value.replace('+', ' ')
                # Basic URL decoding for common characters
                value = value.replace('%20', ' ')
                value = value.replace('%21', '!')
                value = value.replace('%22', '"')
                value = value.replace('%23', '#')
                value = value.replace('%24', '$')
                value = value.replace('%25', '%')
                value = value.replace('%26', '&')
                value = value.replace('%27', "'")
                value = value.replace('%28', '(')
                value = value.replace('%29', ')')
                value = value.replace('%2A', '*')
                value = value.replace('%2B', '+')
                value = value.replace('%2C', ',')
                value = value.replace('%2D', '-')
                value = value.replace('%2E', '.')
                value = value.replace('%2F', '/')

                form_data[key] = value

        return form_data

    except Exception as e:
        log_error(f"Error parsing form data: {e}", "HTTP")
        return {}


def handle_config_update(request):
    """
    Handle configuration update from POST request.

    Args:
        request (bytes): Raw HTTP request data

    Returns:
        str: HTTP response for configuration update
    """
    try:
        # Parse form data
        form_data = parse_form_data(request)
        log_info(f"Config update received: {list(form_data.keys())}", "CONFIG")

        # Validate and process configuration
        config = validate_config_input(form_data)

        # Save configuration
        if save_device_config(config):
            log_info(f"Configuration updated: {config['device']['location']}/{config['device']['name']}", "CONFIG")
            # Redirect back to config page to show updated values
            return "HTTP/1.0 302 Found\r\nLocation: /config\r\n\r\n"
        else:
            log_error("Failed to save configuration", "CONFIG")
            return "HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nFailed to save configuration"

    except Exception as e:
        log_error(f"Configuration update failed: {e}", "CONFIG")
        return f"HTTP/1.0 400 Bad Request\r\nContent-Type: text/plain\r\n\r\nConfiguration update failed: {e}"


def handle_logs_page(request):
    """
    Handle logs page request with filtering and web
