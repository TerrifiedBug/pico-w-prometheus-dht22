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

# Wi-Fi Setup with safety checks
try:
    ssid = secrets["ssid"]
    password = secrets["pw"]

    # Validate credentials are not empty
    if not ssid or not password:
        log_error("WiFi credentials are empty in secrets.py", "NETWORK")
        raise ValueError("WiFi credentials not properly configured")

    log_info(f"WiFi credentials loaded for network: {ssid}", "NETWORK")

except KeyError as e:
    log_error(f"Missing WiFi credential in secrets.py: {e}", "NETWORK")
    raise RuntimeError(f"secrets.py missing required field: {e}")
except Exception as e:
    log_error(f"Error loading WiFi credentials: {e}", "NETWORK")
    raise RuntimeError("WiFi credentials not properly configured")

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
try:
    # Check if OTA is enabled via dynamic configuration
    from device_config import get_ota_config
    ota_config = get_ota_config()

    if ota_config.get("enabled", True):
        from ota_updater import GitHubOTAUpdater
        ota_updater = GitHubOTAUpdater()
        log_info("OTA updater initialized", "OTA")
    else:
        log_info("OTA updater disabled via configuration", "OTA")
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
        download_success = ota_updater.download_update(new_version, None)

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
    Handle health check request with enhanced HTML interface.

    Returns:
        str: HTTP response for health check.
    """
    try:
        # Test sensor reading
        temp, hum = read_dht22()
        sensor_status = "OK" if temp is not None else "FAIL"
        sensor_class = "status-ok" if temp is not None else "status-error"

        # Check OTA status
        ota_status = "Enabled" if ota_updater else "Disabled"
        ota_class = "status-ok" if ota_updater else "status-warn"

        # Get system information with proper tick wraparound handling
        uptime_ms = time.ticks_diff(time.ticks_ms(), boot_ticks)

        # Handle potential negative values from tick wraparound
        if uptime_ms < 0:
            uptime_ms = uptime_ms + (1 << 30)

        uptime_seconds = max(0, uptime_ms // 1000)
        uptime_hours = uptime_seconds // 3600
        uptime_minutes = (uptime_seconds % 3600) // 60
        uptime_days = uptime_hours // 24
        uptime_hours = uptime_hours % 24

        # WiFi information
        wifi_status = "Connected" if wlan.isconnected() else "Disconnected"
        wifi_class = "status-ok" if wlan.isconnected() else "status-error"
        ip_address = wlan.ifconfig()[0] if wlan.isconnected() else "N/A"

        # Memory information
        import gc
        gc.collect()
        free_memory = gc.mem_free()
        memory_mb = round(free_memory / 1024, 1)

        # Memory status based on available memory
        memory_class = "status-ok" if free_memory > 100000 else "status-warn" if free_memory > 50000 else "status-error"

        # Version and device info
        version = ota_updater.get_current_version() if ota_updater else "unknown"
        config = get_config_for_metrics()
        location = config["location"]
        device_name = config["device"]

        # Overall system health
        overall_health = "HEALTHY"
        overall_class = "status-ok"

        if temp is None or not wlan.isconnected():
            overall_health = "DEGRADED"
            overall_class = "status-warn"

        if free_memory < 50000:
            overall_health = "CRITICAL"
            overall_class = "status-error"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>System Health Check</title>
    <style>{get_shared_css()}</style>
    <script>
        function refreshHealth() {{
            window.location.reload();
        }}

        function runSensorTest() {{
            // Simple sensor test - just refresh to get new reading
            refreshHealth();
        }}

        // Auto-refresh every 15 seconds
        setInterval(refreshHealth, 15000);
    </script>
</head>
<body>
    <div class="container">
        <h1>🏥 System Health Check</h1>

        <div class="nav">
            <a href="/">← Back to Dashboard</a>
            <a href="/config">Configuration</a>
            <a href="/logs">System Logs</a>
            <a href="/update/status">OTA Status</a>
        </div>

        <div class="info-section">
            <strong>Device:</strong> {device_name} | <strong>Location:</strong> {location} | <strong>Version:</strong> {version}
        </div>

        <div class="status-grid">
            <div class="status-card {overall_class}">
                <h3>🎯 Overall Health</h3>
                <div class="metric-value">{overall_health}</div>
                <div>System status summary</div>
            </div>

            <div class="status-card {sensor_class}">
                <h3>🌡️ DHT22 Sensor</h3>
                <div class="metric-value">{sensor_status}</div>
                {"<div>" + str(temp) + "°C | " + str(hum) + "%</div>" if temp is not None else "<div>❌ Sensor Error</div>"}
            </div>

            <div class="status-card {wifi_class}">
                <h3>📡 Network</h3>
                <div class="metric-value">{wifi_status}</div>
                <div>IP: {ip_address}</div>
            </div>

            <div class="status-card {ota_class}">
                <h3>🔄 OTA System</h3>
                <div class="metric-value">{ota_status}</div>
                <div>Update system ready</div>
            </div>

            <div class="status-card status-info">
                <h3>⏱️ Uptime</h3>
                <div class="metric-value">{uptime_days}d {uptime_hours:02d}:{uptime_minutes:02d}</div>
                <div>Days:Hours:Minutes</div>
            </div>

            <div class="status-card {memory_class}">
                <h3>💾 Memory</h3>
                <div class="metric-value">{memory_mb}KB</div>
                <div>Free memory available</div>
            </div>
        </div>

        <h2>📊 Detailed Diagnostics</h2>

        <div class="info-section">
            <h3>Sensor Readings</h3>
            <strong>Temperature:</strong> {temp if temp is not None else "ERROR"}°C<br>
            <strong>Humidity:</strong> {hum if hum is not None else "ERROR"}%<br>
            <strong>Sensor Pin:</strong> GPIO {SENSOR_CONFIG['pin']}<br>
            <strong>Read Interval:</strong> {SENSOR_CONFIG['read_interval']}s
        </div>

        <div class="info-section">
            <h3>Network Information</h3>
            <strong>WiFi Status:</strong> {wifi_status}<br>
            <strong>IP Address:</strong> {ip_address}<br>
            <strong>Country Code:</strong> {WIFI_CONFIG['country_code']}<br>
            <strong>SSID:</strong> {ssid if wlan.isconnected() else "Not connected"}
        </div>

        <div class="info-section">
            <h3>System Resources</h3>
            <strong>Free Memory:</strong> {free_memory:,} bytes ({memory_mb}KB)<br>
            <strong>Uptime:</strong> {uptime_days} days, {uptime_hours} hours, {uptime_minutes} minutes<br>
            <strong>Boot Time:</strong> {boot_ticks}ms (ticks)<br>
            <strong>Server Port:</strong> {SERVER_CONFIG['port']}
        </div>

        <div class="info-section">
            <h3>Firmware Information</h3>
            <strong>Version:</strong> {version}<br>
            <strong>OTA Status:</strong> {ota_status}<br>
            <strong>Metrics Endpoint:</strong> {METRICS_ENDPOINT}<br>
            <strong>Device Config:</strong> {location}/{device_name}
        </div>

        <div style="margin-top: 20px;">
            <button onclick="refreshHealth()">🔄 Refresh Health Check</button>
            <button onclick="runSensorTest()" class="success">🧪 Test Sensor</button>
            <a href="/logs"><button class="warning">📋 View Logs</button></a>
            <a href="/update/status"><button class="info">⬆️ Check Updates</button></a>
        </div>

        <div style="margin-top: 20px; text-align: center; color: #6c757d; font-size: 0.9em;">
            Health check auto-refreshes every 15 seconds | Last check: {time.time():.0f}
        </div>
    </div>
</body>
</html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"

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


def get_shared_css():
    """
    Get shared CSS styles for consistent page design.

    Returns:
        str: CSS styles for all pages
    """
    return """
        body { font-family: monospace; margin: 20px; background: #f9f9f9; }
        .container { max-width: 1000px; background: white; padding: 20px; border: 1px solid #ddd; margin: 0 auto; }
        .nav { margin-bottom: 20px; }
        .nav a { color: #007bff; text-decoration: none; margin-right: 20px; }
        .nav a:hover { text-decoration: underline; }
        .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
        .status-card { background: #f8f9fa; padding: 15px; border: 1px solid #dee2e6; border-radius: 4px; }
        .status-card h3 { margin: 0 0 10px 0; color: #495057; }
        .status-ok { border-left: 4px solid #28a745; }
        .status-warn { border-left: 4px solid #ffc107; }
        .status-error { border-left: 4px solid #dc3545; }
        .status-info { border-left: 4px solid #007bff; }
        .metric-value { font-size: 1.2em; font-weight: bold; color: #007bff; }
        .metric-unit { font-size: 0.9em; color: #6c757d; }
        button { background: #007bff; color: white; border: none; cursor: pointer; padding: 8px 16px; margin: 5px; }
        button:hover { background: #0056b3; }
        button.success { background: #28a745; }
        button.success:hover { background: #1e7e34; }
        button.warning { background: #ffc107; color: #212529; }
        button.warning:hover { background: #e0a800; }
        button.danger { background: #dc3545; }
        button.danger:hover { background: #c82333; }
        .progress-bar { background: #e9ecef; height: 20px; border-radius: 4px; overflow: hidden; margin: 10px 0; }
        .progress-fill { background: #007bff; height: 100%; transition: width 0.3s ease; }
        .info-section { background: #e9ecef; padding: 15px; margin: 15px 0; border-left: 4px solid #007bff; }
        .endpoint-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin: 20px 0; }
        .endpoint-card { background: #f8f9fa; padding: 15px; border: 1px solid #dee2e6; text-align: center; }
        .endpoint-card a { color: #007bff; text-decoration: none; font-weight: bold; }
        .endpoint-card a:hover { text-decoration: underline; }
        .endpoint-desc { font-size: 0.9em; color: #6c757d; margin-top: 5px; }
    """

def handle_root_page():
    """
    Handle root page request with dashboard interface.

    Returns:
        str: HTTP response with dashboard
    """
    try:
        # Get system status
        temp, hum = read_dht22()
        sensor_status = "OK" if temp is not None else "FAIL"
        sensor_class = "status-ok" if temp is not None else "status-error"

        # Network status
        wifi_status = "Connected" if wlan.isconnected() else "Disconnected"
        wifi_class = "status-ok" if wlan.isconnected() else "status-error"
        ip_address = wlan.ifconfig()[0] if wlan.isconnected() else "N/A"

        # OTA status
        ota_status = "Enabled" if ota_updater else "Disabled"
        ota_class = "status-ok" if ota_updater else "status-warn"

        # System info
        uptime_ms = time.ticks_diff(time.ticks_ms(), boot_ticks)
        if uptime_ms < 0:
            uptime_ms = uptime_ms + (1 << 30)
        uptime_seconds = max(0, uptime_ms // 1000)
        uptime_hours = uptime_seconds // 3600
        uptime_minutes = (uptime_seconds % 3600) // 60

        # Memory info
        import gc
        gc.collect()
        free_memory = gc.mem_free()
        memory_mb = round(free_memory / 1024, 1)

        # Version info
        version = ota_updater.get_current_version() if ota_updater else "unknown"

        # Device config
        config = get_config_for_metrics()
        location = config["location"]
        device_name = config["device"]

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Pico W Sensor Dashboard</title>
    <style>{get_shared_css()}</style>
    <script>
        function refreshPage() {{
            window.location.reload();
        }}

        // Auto-refresh every 30 seconds
        setInterval(refreshPage, 30000);
    </script>
</head>
<body>
    <div class="container">
        <h1>🌡️ Pico W Sensor Dashboard</h1>

        <div class="info-section">
            <strong>Device:</strong> {device_name} | <strong>Location:</strong> {location} | <strong>Version:</strong> {version}
        </div>

        <div class="status-grid">
            <div class="status-card {sensor_class}">
                <h3>📊 Sensor Status</h3>
                <div class="metric-value">{sensor_status}</div>
                {"<div>🌡️ " + str(temp) + "°C | 💧 " + str(hum) + "%" + "</div>" if temp is not None else "<div>❌ Sensor Error</div>"}
            </div>

            <div class="status-card {wifi_class}">
                <h3>📡 Network</h3>
                <div class="metric-value">{wifi_status}</div>
                <div>IP: {ip_address}</div>
            </div>

            <div class="status-card {ota_class}">
                <h3>🔄 OTA Updates</h3>
                <div class="metric-value">{ota_status}</div>
                <div>Auto-update ready</div>
            </div>

            <div class="status-card status-info">
                <h3>⏱️ System</h3>
                <div class="metric-value">{uptime_hours:02d}:{uptime_minutes:02d}</div>
                <div>💾 {memory_mb}KB free</div>
            </div>
        </div>

        <h2>🔗 Available Services</h2>
        <div class="endpoint-grid">
            <div class="endpoint-card">
                <a href="/health">🏥 Health Check</a>
                <div class="endpoint-desc">System status and diagnostics</div>
            </div>

            <div class="endpoint-card">
                <a href="/config">⚙️ Configuration</a>
                <div class="endpoint-desc">Device and OTA settings</div>
            </div>

            <div class="endpoint-card">
                <a href="/logs">📋 System Logs</a>
                <div class="endpoint-desc">Debug logs and monitoring</div>
            </div>

            <div class="endpoint-card">
                <a href="/update/status">🔄 OTA Status</a>
                <div class="endpoint-desc">Update progress and control</div>
            </div>

            <div class="endpoint-card">
                <a href="/metrics">📈 Metrics</a>
                <div class="endpoint-desc">Prometheus metrics endpoint</div>
            </div>

            <div class="endpoint-card">
                <a href="/update">⬆️ Update Now</a>
                <div class="endpoint-desc">Trigger manual update</div>
            </div>
        </div>

        <div style="margin-top: 20px; text-align: center; color: #6c757d; font-size: 0.9em;">
            Page auto-refreshes every 30 seconds | Last updated: {time.time():.0f}
        </div>
    </div>
</body>
</html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"

    except Exception as e:
        log_error(f"Root page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nDashboard error: {e}"

def handle_logs_page(request):
    """
    Handle logs page request with filtering and web interface.

    Args:
        request (bytes): Raw HTTP request data

    Returns:
        str: HTTP response with logs interface
    """
    try:
        # Parse query parameters for filtering
        request_str = request.decode('utf-8')
        query_params = {}

        # Extract query string from request
        if '?' in request_str:
            query_string = request_str.split('?')[1].split(' ')[0]
            for param in query_string.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    query_params[key] = value

        # Get filter parameters
        level_filter = query_params.get('level', 'ALL')
        category_filter = query_params.get('category', 'ALL')
        action = query_params.get('action', '')

        # Handle clear logs action
        if action == 'clear':
            logger = get_logger()
            logger.clear_logs()
            log_info("Logs cleared via web interface", "SYSTEM")
            # Redirect to remove action parameter
            return "HTTP/1.0 302 Found\r\nLocation: /logs\r\n\r\n"

        # Get logger and statistics
        logger = get_logger()
        stats = logger.get_statistics()

        # Get filtered logs
        logs = logger.get_logs(level_filter, category_filter, last_n=100)

        # Format logs for display
        log_lines = []
        for log in logs:
            timestamp_str = f"+{log['t']}s"
            line = f"[{timestamp_str:>6}] {log['l']:5} {log['c']:7}: {log['m']}"
            log_lines.append(line)

        logs_text = "\n".join(log_lines) if log_lines else "No logs found matching criteria."

        # Generate HTML interface
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>System Logs</title>
    <style>
        body {{ font-family: monospace; margin: 20px; background: #f9f9f9; }}
        .container {{ max-width: 1200px; background: white; padding: 20px; border: 1px solid #ddd; }}
        .controls {{ background: #e9ecef; padding: 15px; margin-bottom: 20px; border-left: 4px solid #007bff; }}
        .controls select, .controls button {{ margin: 5px; padding: 8px; font-family: monospace; }}
        .stats {{ background: #f8f9fa; padding: 10px; margin-bottom: 15px; border: 1px solid #dee2e6; }}
        .logs {{ background: #000; color: #0f0; padding: 15px; font-family: 'Courier New', monospace; font-size: 12px; height: 500px; overflow-y: auto; white-space: pre-wrap; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #007bff; text-decoration: none; margin-right: 20px; }}
        .nav a:hover {{ text-decoration: underline; }}
        button {{ background: #007bff; color: white; border: none; cursor: pointer; padding: 8px 16px; }}
        button:hover {{ background: #0056b3; }}
        button.danger {{ background: #dc3545; }}
        button.danger:hover {{ background: #c82333; }}
        .auto-refresh {{ margin-left: 10px; }}
    </style>
    <script>
        function filterLogs() {{
            var level = document.getElementById('level').value;
            var category = document.getElementById('category').value;
            var url = '/logs?level=' + level + '&category=' + category;
            window.location.href = url;
        }}

        function clearLogs() {{
            if (confirm('Are you sure you want to clear all logs?')) {{
                window.location.href = '/logs?action=clear';
            }}
        }}

        function refreshLogs() {{
            window.location.reload();
        }}

        // Auto-refresh every 10 seconds if checkbox is checked
        setInterval(function() {{
            if (document.getElementById('autoRefresh').checked) {{
                refreshLogs();
            }}
        }}, 10000);
    </script>
</head>
<body>
    <div class="container">
        <h1>System Logs</h1>

        <div class="nav">
            <a href="/">← Back to Main Menu</a>
            <a href="/health">Health Check</a>
            <a href="/config">Configuration</a>
            <a href="/update/status">OTA Status</a>
        </div>

        <div class="stats">
            <strong>Log Statistics:</strong>
            Entries: {stats['total_entries']}/{stats['max_entries']} |
            Memory: {stats['memory_usage_kb']}KB/{stats['max_memory_kb']}KB |
            Uptime: {stats['uptime_seconds']}s |
            Errors: {stats['logs_by_level']['ERROR']} |
            Warnings: {stats['logs_by_level']['WARN']}
        </div>

        <div class="controls">
            <label>Level:</label>
            <select id="level" onchange="filterLogs()">
                <option value="ALL" {"selected" if level_filter == "ALL" else ""}>ALL</option>
                <option value="ERROR" {"selected" if level_filter == "ERROR" else ""}>ERROR</option>
                <option value="WARN" {"selected" if level_filter == "WARN" else ""}>WARN</option>
                <option value="INFO" {"selected" if level_filter == "INFO" else ""}>INFO</option>
                <option value="DEBUG" {"selected" if level_filter == "DEBUG" else ""}>DEBUG</option>
            </select>

            <label>Category:</label>
            <select id="category" onchange="filterLogs()">
                <option value="ALL" {"selected" if category_filter == "ALL" else ""}>ALL</option>
                <option value="SYSTEM" {"selected" if category_filter == "SYSTEM" else ""}>SYSTEM</option>
                <option value="OTA" {"selected" if category_filter == "OTA" else ""}>OTA</option>
                <option value="SENSOR" {"selected" if category_filter == "SENSOR" else ""}>SENSOR</option>
                <option value="CONFIG" {"selected" if category_filter == "CONFIG" else ""}>CONFIG</option>
                <option value="NETWORK" {"selected" if category_filter == "NETWORK" else ""}>NETWORK</option>
                <option value="HTTP" {"selected" if category_filter == "HTTP" else ""}>HTTP</option>
            </select>

            <button onclick="refreshLogs()">Refresh</button>
            <button class="danger" onclick="clearLogs()">Clear Logs</button>

            <label class="auto-refresh">
                <input type="checkbox" id="autoRefresh"> Auto-refresh (10s)
            </label>
        </div>

        <div class="logs">{logs_text}</div>

        <div style="margin-top: 15px; font-size: 12px; color: #666;">
            Showing last 100 entries. Logs are stored in memory only and will be lost on restart.
        </div>
    </div>
</body>
</html>"""

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{html}"

    except Exception as e:
        log_error(f"Logs page error: {e}", "HTTP")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nLogs page error: {e}"


# HTTP Server Setup and Request Handling
def handle_request(cl, request):
    """
    Handle incoming HTTP requests with improved routing and error handling.

    Args:
        cl: Client socket connection.
        request (bytes): Raw HTTP request data.
    """
    try:
        # Parse request
        request_str = request.decode('utf-8')
        lines = request_str.split('\r\n')
        if not lines:
            cl.send("HTTP/1.0 400 Bad Request\r\n\r\n")
            return

        # Extract method and path
        request_line = lines[0]
        parts = request_line.split(' ')
        if len(parts) < 2:
            cl.send("HTTP/1.0 400 Bad Request\r\n\r\n")
            return

        method = parts[0]
        path = parts[1]

        # Remove query parameters from path for routing
        if '?' in path:
            path = path.split('?')[0]

        log_debug(f"HTTP {method} {path}", "HTTP")

        # Route requests
        if method == "GET" and path == METRICS_ENDPOINT:
            # Prometheus metrics endpoint
            temp, hum = read_dht22()
            if temp is not None and hum is not None:
                metrics = format_metrics(temp, hum)
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n")
                cl.send(metrics)
            else:
                cl.send("HTTP/1.0 503 Service Unavailable\r\nContent-Type: text/plain\r\n\r\nSensor unavailable")

        elif method == "GET" and path == "/health":
            # Health check endpoint
            response = handle_health_check()
            cl.send(response)

        elif method == "GET" and path == "/config":
            # Configuration page
            response = handle_config_page()
            cl.send(response)

        elif method == "POST" and path == "/config":
            # Configuration update
            response = handle_config_update(request)
            cl.send(response)

        elif method == "GET" and path == "/logs":
            # Logs page endpoint
            response = handle_logs_page(request)
            cl.send(response)

        elif method == "GET" and path == "/update/status":
            # Update status endpoint
            response = handle_update_status()
            cl.send(response)

        elif method == "GET" and path == "/update":
            # Manual update trigger
            response = handle_update_request_delayed()
            cl.send(response)

        elif method == "GET" and path == "/":
            # Root endpoint - dashboard interface
            response = handle_root_page()
            cl.send(response)

        else:
            # 404 Not Found
            cl.send("HTTP/1.0 404 Not Found\r\nContent-Type: text/plain\r\n\r\nEndpoint not found")

    except Exception as e:
        log_error(f"Request handling error: {e}", "HTTP")
        try:
            cl.send("HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nInternal server error")
        except:
            pass  # Connection might be closed


# Main server loop
def run_server():
    """
    Run the main HTTP server loop with improved error handling and OTA integration.
    """
    addr = socket.getaddrinfo(SERVER_CONFIG["host"], SERVER_CONFIG["port"])[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)

    log_info(f"HTTP server listening on {SERVER_CONFIG['host']}:{SERVER_CONFIG['port']}", "SYSTEM")

    while True:
        try:
            # Check for scheduled updates
            if pending_update["scheduled"] and time.time() >= pending_update["start_time"]:
                perform_scheduled_update()

            # Accept connections with timeout
            s.settimeout(1.0)  # 1 second timeout
            try:
                cl, addr = s.accept()
                log_debug(f"Connection from {addr}", "HTTP")
            except OSError:
                continue  # Timeout, continue loop

            # Handle request
            try:
                cl.settimeout(10.0)  # 10 second timeout for client operations
                request = cl.recv(1024)
                if request:
                    handle_request(cl, request)
            except Exception as e:
                log_error(f"Client handling error: {e}", "HTTP")
            finally:
                try:
                    cl.close()
                except:
                    pass

        except KeyboardInterrupt:
            log_info("Server shutdown requested", "SYSTEM")
            break
        except Exception as e:
            log_error(f"Server error: {e}", "SYSTEM")
            time.sleep(1)  # Brief pause before retrying

    s.close()
    log_info("HTTP server stopped", "SYSTEM")


# Start the server
if __name__ == "__main__":
    try:
        log_info("Starting Pico W Prometheus DHT22 sensor server", "SYSTEM")
        run_server()
    except Exception as e:
        log_error(f"Fatal error: {e}", "SYSTEM")
        raise
