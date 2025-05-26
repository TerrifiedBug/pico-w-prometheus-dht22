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
    print("Connecting to Wi-Fi...")
    wlan.connect(ssid, password)

    max_wait = 20  # Increased timeout
    while max_wait > 0:
        status = wlan.status()

        if status == 3:  # Connected
            print("Connected, IP =", wlan.ifconfig()[0])
            return True
        elif status < 0:  # Error states (-1, -2, -3)
            print(f"Connection failed with status {status}, retrying...")
            wlan.disconnect()
            time.sleep(2)
            wlan.connect(ssid, password)
            max_wait = 20  # Reset timeout for retry
        else:
            print(f"Connecting... (status: {status}, {max_wait}s remaining)")

        max_wait -= 1
        time.sleep(1)

    # If we get here, connection failed
    print("WiFi connection timeout")
    return False


wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# Optional: set static IP (adjust as needed)
# wlan.ifconfig(('10.1.1.161','255.255.255.0','10.1.1.1','8.8.8.8'))

# Connect with improved reliability
if not connect_wifi():
    print("Initial connection failed, trying once more...")
    time.sleep(5)
    if not connect_wifi():
        raise RuntimeError("Wi-Fi connection failed after retries")

# DHT22 Sensor Setup
sensor = dht.DHT22(Pin(SENSOR_CONFIG["pin"]))

# OTA Updater Setup
ota_updater = None
if OTA_CONFIG["enabled"]:
    try:
        from ota_updater import GitHubOTAUpdater
        ota_updater = GitHubOTAUpdater()
        print("OTA updater initialized")
    except Exception as e:
        print(f"Failed to initialize OTA updater: {e}")


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
        return round(t, 2), round(h, 2)
    except Exception as e:
        print("Sensor read failed:", e)
        return None, None


# HTTP Server (Prometheus-style)
def format_metrics(temperature, humidity):
    """
    Format temperature, humidity, and system health as Prometheus metrics.

    Args:
        temperature (float): Temperature reading in Celsius.
        humidity (float): Humidity reading as a percentage.

    Returns:
        str: Formatted Prometheus metrics string with HELP and TYPE comments.
    """
    # Basic sensor metrics
    metrics = []

    # Temperature and humidity
    metrics.extend([
        f"# HELP {METRIC_NAMES['temperature']} Temperature in Celsius",
        f"# TYPE {METRIC_NAMES['temperature']} gauge",
        f"{METRIC_NAMES['temperature']} {temperature}",
        f"# HELP {METRIC_NAMES['humidity']} Humidity in Percent",
        f"# TYPE {METRIC_NAMES['humidity']} gauge",
        f"{METRIC_NAMES['humidity']} {humidity}",
    ])

    # System health metrics
    sensor_status = 1 if temperature is not None else 0
    ota_status = 1 if ota_updater else 0

    metrics.extend([
        "# HELP pico_sensor_status Sensor health status (1=OK, 0=FAIL)",
        "# TYPE pico_sensor_status gauge",
        f"pico_sensor_status {sensor_status}",
        "# HELP pico_ota_status OTA system status (1=enabled, 0=disabled)",
        "# TYPE pico_ota_status gauge",
        f"pico_ota_status {ota_status}",
    ])

    # Version information
    if ota_updater:
        current_version = ota_updater.get_current_version()
        metrics.extend([
            "# HELP pico_version_info Current firmware version",
            "# TYPE pico_version_info gauge",
            f'pico_version_info{{version="{current_version}"}} 1',
        ])

    # System uptime (actual time since boot using ticks)
    uptime_ms = time.ticks_diff(time.ticks_ms(), boot_ticks)
    uptime_seconds = uptime_ms // 1000
    metrics.extend([
        "# HELP pico_uptime_seconds Actual uptime in seconds since boot",
        "# TYPE pico_uptime_seconds counter",
        f"pico_uptime_seconds {uptime_seconds}",
    ])


    return "\n".join(metrics) + "\n"


def handle_update_request_delayed():
    """
    Handle OTA update request with delayed execution and redirect to status page.

    Returns:
        str: HTTP response for update request.
    """
    if not ota_updater:
        return "HTTP/1.0 503 Service Unavailable\r\nContent-Type: text/plain\r\n\r\nOTA not enabled"

    try:
        print("Manual update requested")

        # Check if update is already scheduled
        if pending_update["scheduled"]:
            # Redirect to status page if update already scheduled
            return "HTTP/1.0 302 Found\r\nLocation: /update/status\r\n\r\n"

        # Check for available updates
        has_update, new_version, _ = ota_updater.check_for_updates()

        if not has_update:
            return "HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nNo updates available\n\nCurrent version is up to date."

        # Get current version for display
        current_version = ota_updater.get_current_version()

        # Schedule update for 10 seconds later
        pending_update["scheduled"] = True
        pending_update["version"] = new_version
        pending_update["current_version"] = current_version
        pending_update["start_time"] = time.time() + 10

        print(f"Update to {new_version} scheduled for {pending_update['start_time']}")

        # Return HTML with auto-redirect to status page
        html = f"""HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="3;url=/update/status">
    <title>Update Scheduled - Pico W</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            max-width: 600px;
        }}
        .success {{ color: #28a745; font-size: 24px; margin-bottom: 20px; }}
        .info {{ background: #e7f3ff; padding: 15px; border-radius: 5px; margin: 15px 0; }}
        .redirect {{ color: #007bff; font-style: italic; }}
        @media (max-width: 600px) {{
            body {{ margin: 10px; }}
            .container {{ padding: 20px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1 class="success">✓ Update Scheduled Successfully!</h1>

        <div class="info">
            <p><strong>Current Version:</strong> {current_version}</p>
            <p><strong>Target Version:</strong> {new_version}</p>
            <p><strong>Update will start in:</strong> 10 seconds</p>
        </div>

        <h3>What happens next:</h3>
        <ol>
            <li>You'll be redirected to the status page in 3 seconds</li>
            <li>The update will begin automatically after 10 seconds</li>
            <li>Device will restart during update (normal behavior)</li>
            <li>Wait 30-60 seconds for update to complete</li>
            <li>Visit /health to confirm new version</li>
        </ol>

        <p class="redirect">Redirecting to status page in 3 seconds...</p>
        <p><a href="/update/status">Click here if not redirected automatically</a></p>
    </div>
</body>
</html>"""
        return html

    except Exception as e:
        print(f"Update request failed: {e}")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nUpdate scheduling failed: {e}"


def perform_scheduled_update():
    """
    Perform the scheduled OTA update with progress tracking.
    """
    try:
        print(f"Starting scheduled update to version {pending_update['version']}")

        # Update status: Starting download
        pending_update["status"] = "downloading"
        pending_update["progress"] = 25
        pending_update["message"] = "Downloading update files..."

        # Check for updates again (quick check)
        has_update, new_version, _ = ota_updater.check_for_updates()
        if not has_update:
            pending_update["scheduled"] = False
            pending_update["status"] = "idle"
            return

        # Update status: Downloading files
        print("Downloading update files...")
        download_success = ota_updater.download_update(new_version)

        if not download_success:
            pending_update["status"] = "failed"
            pending_update["message"] = "Download failed"
            pending_update["scheduled"] = False
            return

        # Update status: Applying update
        pending_update["status"] = "applying"
        pending_update["progress"] = 75
        pending_update["message"] = "Applying update and backing up files..."
        print("Applying update...")

        # Small delay to allow status page to show this step
        time.sleep(1)

        # Apply the update
        apply_success = ota_updater.apply_update(new_version)

        if apply_success:
            # Update status: About to restart
            pending_update["status"] = "restarting"
            pending_update["progress"] = 100
            pending_update["message"] = "Update complete, restarting device..."
            print("Update completed successfully, device will restart in 2 seconds")

            # Brief delay to show final status
            time.sleep(2)

            # Device will restart here
            import machine
            machine.reset()
        else:
            pending_update["status"] = "failed"
            pending_update["message"] = "Update application failed"
            pending_update["scheduled"] = False
            print("Update failed")

    except Exception as e:
        print(f"Scheduled update failed: {e}")
        pending_update["status"] = "failed"
        pending_update["message"] = f"Update error: {str(e)}"
        pending_update["scheduled"] = False


def handle_update_request():
    """
    Handle OTA update request (legacy function kept for compatibility).

    Returns:
        str: HTTP response for update request.
    """
    if not ota_updater:
        return "HTTP/1.0 503 Service Unavailable\r\n\r\nOTA not enabled"

    try:
        print("Manual update requested")
        has_update, new_version, _ = ota_updater.check_for_updates()

        if not has_update:
            return "HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nNo updates available"

        print(f"Starting update to version {new_version}")
        # Note: This will restart the device if successful
        success = ota_updater.perform_update()

        if success:
            return "HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nUpdate completed, restarting..."
        else:
            return "HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nUpdate failed"

    except Exception as e:
        print(f"Update request failed: {e}")
        return "HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nUpdate error"


def handle_update_status():
    """
    Handle update status request with HTML interface and live countdown.

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
                status_color = "#ff6600"
                refresh_interval = 2
                progress_width = max(10, 100 - (time_remaining * 10))
            elif update_status == "downloading":
                status_text = "DOWNLOADING UPDATE FILES"
                status_color = "#007bff"
                refresh_interval = 1
                progress_width = progress
            elif update_status == "applying":
                status_text = "APPLYING UPDATE"
                status_color = "#ffc107"
                refresh_interval = 1
                progress_width = progress
            elif update_status == "restarting":
                status_text = "RESTARTING DEVICE"
                status_color = "#dc3545"
                refresh_interval = 3
                progress_width = 100
            elif update_status == "failed":
                status_text = "UPDATE FAILED"
                status_color = "#dc3545"
                refresh_interval = 10
                progress_width = 0
            else:
                status_text = "UPDATE STARTING NOW!"
                status_color = "#dc3545"
                refresh_interval = 1
                progress_width = 10

            # Return HTML with live countdown - modern design
            html = f"""HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="{refresh_interval}">
    <title>OTA Update Status - Pico W</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }}
        .dashboard {{
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            color: white;
            margin-bottom: 40px;
        }}
        .header h1 {{
            font-size: 42px;
            margin: 0;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        .header p {{
            font-size: 18px;
            margin: 10px 0;
            opacity: 0.9;
        }}
        .countdown-card {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}
        .countdown-value {{
            font-size: 72px;
            font-weight: bold;
            color: {status_color};
            margin: 20px 0;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
        }}
        .countdown-label {{
            font-size: 24px;
            color: #666;
            margin-bottom: 20px;
        }}
        .status-badge {{
            display: inline-block;
            padding: 12px 24px;
            background-color: {status_color};
            color: white;
            border-radius: 25px;
            font-weight: bold;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .info-card {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }}
        .info-card:hover {{
            transform: translateY(-5px);
        }}
        .info-label {{
            font-weight: bold;
            color: #495057;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
        }}
        .info-value {{
            color: #212529;
            font-size: 20px;
            font-weight: 600;
        }}
        .progress-container {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
            margin: 30px 0;
        }}
        .progress-bar {{
            width: 100%;
            height: 30px;
            background-color: #e9ecef;
            border-radius: 15px;
            overflow: hidden;
            margin: 20px 0;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, {status_color} 0%, {status_color}dd 100%);
            transition: width 1s ease;
            border-radius: 15px;
            position: relative;
        }}
        .progress-fill::after {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.3) 50%, transparent 100%);
            animation: shimmer 2s infinite;
        }}
        @keyframes shimmer {{
            0% {{ transform: translateX(-100%); }}
            100% {{ transform: translateX(100%); }}
        }}
        .process-steps {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
            margin: 30px 0;
        }}
        .process-steps h3 {{
            color: #333;
            margin-bottom: 25px;
            font-size: 22px;
        }}
        .step-list {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .step-item {{
            display: flex;
            align-items: center;
            padding: 15px 0;
            border-bottom: 1px solid #eee;
            font-size: 16px;
        }}
        .step-item:last-child {{
            border-bottom: none;
        }}
        .step-icon {{
            font-size: 24px;
            margin-right: 15px;
            width: 30px;
        }}
        .current-step {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
            margin: 30px 0;
            border-left: 5px solid {status_color};
        }}
        .current-step-label {{
            font-weight: bold;
            color: {status_color};
            font-size: 18px;
            margin-bottom: 10px;
        }}
        .current-step-message {{
            color: #333;
            font-size: 16px;
        }}
        .actions {{
            text-align: center;
            margin: 30px 0;
        }}
        .btn {{
            display: inline-block;
            padding: 12px 24px;
            background: rgba(255,255,255,0.2);
            color: white;
            text-decoration: none;
            border-radius: 25px;
            margin: 0 10px;
            font-weight: 500;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
        }}
        .btn:hover {{
            background: rgba(255,255,255,0.3);
            transform: translateY(-2px);
        }}
        .footer {{
            text-align: center;
            color: white;
            margin-top: 40px;
            opacity: 0.8;
        }}
        @media (max-width: 768px) {{
            body {{ padding: 10px; }}
            .header h1 {{ font-size: 32px; }}
            .countdown-value {{ font-size: 48px; }}
            .info-grid {{ grid-template-columns: 1fr; }}
            .countdown-card {{ padding: 25px; }}
        }}
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1>🔄 OTA Update in Progress</h1>
            <p>Firmware Update Status Monitor</p>
        </div>

        <div class="countdown-card">
            <div class="countdown-label">
                {status_text}
            </div>
            <div class="countdown-value">
                {time_remaining if time_remaining > 0 else "ACTIVE"}
                {"s" if time_remaining > 0 else ""}
            </div>
            <div class="status-badge">{status_text}</div>
        </div>

        <div class="info-grid">
            <div class="info-card">
                <div class="info-label">Current Version</div>
                <div class="info-value">{current_version}</div>
            </div>
            <div class="info-card">
                <div class="info-label">Target Version</div>
                <div class="info-value">{target_version}</div>
            </div>
            <div class="info-card">
                <div class="info-label">Repository</div>
                <div class="info-value">{status_info['repo']}</div>
            </div>
            <div class="info-card">
                <div class="info-label">Progress</div>
                <div class="info-value">{progress_width}%</div>
            </div>
        </div>

        <div class="progress-container">
            <h3>Update Progress</h3>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {progress_width}%"></div>
            </div>
        </div>

        <div class="process-steps">
            <h3>Update Process</h3>
            <ul class="step-list">
                <li class="step-item">
                    <span class="step-icon">✅</span>
                    Update scheduled
                </li>
                <li class="step-item">
                    <span class="step-icon">{"✅" if time_remaining <= 0 else "⏳"}</span>
                    Waiting for start time
                </li>
                <li class="step-item">
                    <span class="step-icon">{"✅" if update_status in ["applying", "restarting"] else "⏳"}</span>
                    Download update files
                </li>
                <li class="step-item">
                    <span class="step-icon">{"✅" if update_status == "restarting" else "⏳"}</span>
                    Apply update and backup
                </li>
                <li class="step-item">
                    <span class="step-icon">{"✅" if update_status == "restarting" else "⏳"}</span>
                    Device restart
                </li>
            </ul>
        </div>

        <div class="current-step">
            <div class="current-step-label">Current Step</div>
            <div class="current-step-message">{message}</div>
        </div>

        <div class="actions">
            <a href="/" class="btn">🏠 Dashboard</a>
            <a href="/health" class="btn">🏥 Health Check</a>
        </div>

        <div class="footer">
            <p>📡 Auto-refresh: {refresh_interval} seconds</p>
            <p>After restart, visit <a href="/health" style="color: white;">/health</a> to verify update</p>
        </div>
    </div>
</body>
</html>"""
            return html
        else:
            # No pending update - show normal status
            html = f"""HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OTA Status - Pico W</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            max-width: 700px;
        }}
        .status-header {{ color: #28a745; font-size: 28px; margin-bottom: 20px; }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin: 20px 0;
        }}
        .info-item {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #28a745;
        }}
        .info-label {{ font-weight: bold; color: #495057; }}
        .info-value {{ color: #212529; margin-top: 5px; }}
        .actions {{ margin: 20px 0; }}
        .btn {{
            display: inline-block;
            padding: 10px 20px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            margin-right: 10px;
        }}
        @media (max-width: 600px) {{
            body {{ margin: 10px; }}
            .container {{ padding: 20px; }}
            .info-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1 class="status-header">✅ OTA System Ready</h1>

        <div class="info-grid">
            <div class="info-item">
                <div class="info-label">Current Version</div>
                <div class="info-value">{current_version}</div>
            </div>
            <div class="info-item">
                <div class="info-label">OTA Enabled</div>
                <div class="info-value">{"Yes" if status_info['ota_enabled'] else "No"}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Auto Check</div>
                <div class="info-value">{"Yes" if status_info['auto_check'] else "No"}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Repository</div>
                <div class="info-value">{status_info['repo']}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Branch</div>
                <div class="info-value">{status_info['branch']}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Update Files</div>
                <div class="info-value">{', '.join(status_info['update_files'])}</div>
            </div>
        </div>

        <div class="actions">
            <a href="/update" class="btn">Check for Updates</a>
            <a href="/health" class="btn">Health Check</a>
            <a href="/" class="btn">Home</a>
        </div>

        <p><strong>Status:</strong> No pending updates. System ready for OTA updates.</p>
    </div>
</body>
</html>"""
            return html

    except Exception as e:
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nStatus error: {e}"


def handle_health_check():
    """
    Handle health check request with comprehensive system dashboard.

    Returns:
        str: HTTP response with health check information.
    """
    try:
        # Get current sensor readings
        temp, hum = read_dht22()
        sensor_status = "OK" if temp is not None else "FAIL"
        sensor_color = "#28a745" if temp is not None else "#dc3545"

        # Get system information
        uptime_ms = time.ticks_diff(time.ticks_ms(), boot_ticks)
        uptime_seconds = uptime_ms // 1000
        uptime_hours = uptime_seconds // 3600
        uptime_minutes = (uptime_seconds % 3600) // 60
        uptime_secs = uptime_seconds % 60

        # WiFi information
        wifi_status = "Connected" if wlan.isconnected() else "Disconnected"
        wifi_color = "#28a745" if wlan.isconnected() else "#dc3545"
        ip_address = wlan.ifconfig()[0] if wlan.isconnected() else "N/A"
        wifi_rssi = wlan.status('rssi') if wlan.isconnected() else "N/A"

        # OTA information
        ota_status = "Enabled" if ota_updater else "Disabled"
        ota_color = "#28a745" if ota_updater else "#ffc107"
        current_version = ota_updater.get_current_version() if ota_updater else "unknown"

        # Memory information (basic)
        import gc
        gc.collect()
        free_memory = gc.mem_free()

        # Return comprehensive HTML dashboard
        html = f"""HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="10">
    <title>System Health - Pico W</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            max-width: 900px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            border-bottom: 2px solid #e9ecef;
            padding-bottom: 20px;
        }}
        .status-header {{ color: #28a745; font-size: 28px; margin: 0; }}
        .last-updated {{ color: #6c757d; font-size: 14px; }}
        .sensor-readings {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin: 30px 0;
        }}
        .sensor-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }}
        .sensor-value {{
            font-size: 36px;
            font-weight: bold;
            margin: 10px 0;
        }}
        .sensor-label {{
            font-size: 16px;
            opacity: 0.9;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin: 30px 0;
        }}
        .info-item {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #007bff;
        }}
        .info-label {{
            font-weight: bold;
            color: #495057;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .info-value {{
            color: #212529;
            margin-top: 8px;
            font-size: 18px;
        }}
        .status-indicator {{
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }}
        .actions {{
            margin: 30px 0;
            text-align: center;
        }}
        .btn {{
            display: inline-block;
            padding: 12px 24px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 6px;
            margin: 0 10px;
            font-weight: 500;
            transition: background-color 0.3s;
        }}
        .btn:hover {{
            background-color: #0056b3;
        }}
        .btn-success {{ background-color: #28a745; }}
        .btn-success:hover {{ background-color: #1e7e34; }}
        .btn-warning {{ background-color: #ffc107; color: #212529; }}
        .btn-warning:hover {{ background-color: #e0a800; }}
        .refresh-note {{
            color: #6c757d;
            font-style: italic;
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #e9ecef;
        }}
        @media (max-width: 768px) {{
            body {{ margin: 10px; }}
            .container {{ padding: 20px; }}
            .header {{ flex-direction: column; text-align: center; }}
            .sensor-readings {{ grid-template-columns: 1fr; }}
            .info-grid {{ grid-template-columns: 1fr; }}
            .actions {{ margin: 20px 0; }}
            .btn {{ margin: 5px; display: block; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="status-header">🏥 System Health Dashboard</h1>
            <div class="last-updated">
                Last updated: {time.time():.0f}<br>
                Auto-refresh: 10 seconds
            </div>
        </div>

        <div class="sensor-readings">
            <div class="sensor-card">
                <div class="sensor-label">🌡️ Temperature</div>
                <div class="sensor-value">{temp if temp is not None else "ERROR"}°C</div>
            </div>
            <div class="sensor-card">
                <div class="sensor-label">💧 Humidity</div>
                <div class="sensor-value">{hum if hum is not None else "ERROR"}%</div>
            </div>
        </div>

        <div class="info-grid">
            <div class="info-item">
                <div class="info-label">Sensor Status</div>
                <div class="info-value">
                    <span class="status-indicator" style="background-color: {sensor_color};"></span>
                    {sensor_status}
                </div>
            </div>
            <div class="info-item">
                <div class="info-label">WiFi Connection</div>
                <div class="info-value">
                    <span class="status-indicator" style="background-color: {wifi_color};"></span>
                    {wifi_status}
                </div>
            </div>
            <div class="info-item">
                <div class="info-label">IP Address</div>
                <div class="info-value">{ip_address}</div>
            </div>
            <div class="info-item">
                <div class="info-label">WiFi Signal</div>
                <div class="info-value">{wifi_rssi} dBm</div>
            </div>
            <div class="info-item">
                <div class="info-label">OTA Updates</div>
                <div class="info-value">
                    <span class="status-indicator" style="background-color: {ota_color};"></span>
                    {ota_status}
                </div>
            </div>
            <div class="info-item">
                <div class="info-label">Firmware Version</div>
                <div class="info-value">{current_version}</div>
            </div>
            <div class="info-item">
                <div class="info-label">System Uptime</div>
                <div class="info-value">{uptime_hours:02d}:{uptime_minutes:02d}:{uptime_secs:02d}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Free Memory</div>
                <div class="info-value">{free_memory:,} bytes</div>
            </div>
        </div>

        <div class="actions">
            <a href="/" class="btn">🏠 Dashboard</a>
            <a href="/update/status" class="btn btn-success">🔄 Update Status</a>
            <a href="/update" class="btn btn-warning">⚡ Check Updates</a>
            <a href="/metrics" class="btn">📊 Metrics</a>
        </div>

        <div class="refresh-note">
            📡 This page refreshes automatically every 10 seconds to show live data<br>
            🔧 System monitoring for Pico W DHT22 sensor device
        </div>
    </div>
</body>
</html>"""
        return html

    except Exception as e:
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nHealth check failed: {e}"


addr = socket.getaddrinfo(SERVER_CONFIG["host"], SERVER_CONFIG["port"])[0][-1]
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(addr)
s.listen(1)

print("Listening on http://%s%s" % (wlan.ifconfig()[0], METRICS_ENDPOINT))

while True:
    try:
        # Check for pending scheduled updates
        if pending_update["scheduled"] and time.time() >= pending_update["start_time"]:
            perform_scheduled_update()
            # Note: perform_scheduled_update() will restart the device if successful

        cl, addr = s.accept()
        print("Client connected from", addr)
        request = cl.recv(1024)
        request_line = request.decode().split("\r\n")[0]

        # Extract the path from the request line for exact matching
        try:
            request_parts = request_line.split()
            if len(request_parts) >= 2:
                method = request_parts[0]
                path = request_parts[1]
            else:
                method = ""
                path = ""
        except:
            method = ""
            path = ""

        # Route requests to appropriate handlers using exact path matching
        if method == "GET" and path == METRICS_ENDPOINT:
            # Prometheus metrics endpoint
            temp, hum = read_dht22()
            if temp is not None:
                response = format_metrics(temp, hum)
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n")
                cl.send(response)
            else:
                cl.send("HTTP/1.0 500 Internal Server Error\r\n\r\n")
                cl.send("Sensor error")

        elif method == "GET" and path == "/update/status":
            # Update status endpoint - check this BEFORE /update
            response = handle_update_status()
            cl.send(response)

        elif method == "GET" and path == "/update":
            # OTA update endpoint with delayed execution
            response = handle_update_request_delayed()
            cl.send(response)

        elif method == "GET" and path == "/health":
            # Health check endpoint
            response = handle_health_check()
            cl.send(response)

        elif method == "GET" and path == "/":
            # Root endpoint - main dashboard
            try:
                # Get current sensor readings for dashboard
                temp, hum = read_dht22()

                # Get basic system info
                uptime_ms = time.ticks_diff(time.ticks_ms(), boot_ticks)
                uptime_seconds = uptime_ms // 1000
                uptime_hours = uptime_seconds // 3600
                uptime_minutes = (uptime_seconds % 3600) // 60

                # WiFi and system status
                wifi_status = "Connected" if wlan.isconnected() else "Disconnected"
                wifi_color = "#28a745" if wlan.isconnected() else "#dc3545"
                ip_address = wlan.ifconfig()[0] if wlan.isconnected() else "N/A"

                # OTA status
                current_version = ota_updater.get_current_version() if ota_updater else "unknown"

                # Check if update is pending
                update_status = "No updates pending"
                update_color = "#28a745"
                if pending_update["scheduled"]:
                    time_remaining = max(0, int(pending_update["start_time"] - time.time()))
                    if time_remaining > 0:
                        update_status = f"Update in {time_remaining}s"
                        update_color = "#ffc107"
                    else:
                        update_status = "Update in progress"
                        update_color = "#dc3545"

                html = f"""HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="30">
    <title>Pico W Dashboard</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }}
        .dashboard {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            color: white;
            margin-bottom: 40px;
        }}
        .header h1 {{
            font-size: 42px;
            margin: 0;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        .header p {{
            font-size: 18px;
            margin: 10px 0;
            opacity: 0.9;
        }}
        .cards-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 25px;
            margin-bottom: 40px;
        }}
        .card {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }}
        .card:hover {{
            transform: translateY(-5px);
        }}
        .card-header {{
            display: flex;
            align-items: center;
            margin-bottom: 20px;
        }}
        .card-icon {{
            font-size: 32px;
            margin-right: 15px;
        }}
        .card-title {{
            font-size: 20px;
            font-weight: bold;
            color: #333;
            margin: 0;
        }}
        .sensor-value {{
            font-size: 48px;
            font-weight: bold;
            text-align: center;
            margin: 20px 0;
            color: #667eea;
        }}
        .sensor-unit {{
            font-size: 18px;
            color: #666;
        }}
        .status-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }}
        .status-item:last-child {{
            border-bottom: none;
        }}
        .status-label {{
            font-weight: 500;
            color: #555;
        }}
        .status-value {{
            font-weight: bold;
        }}
        .status-indicator {{
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-left: 8px;
        }}
        .actions-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }}
        .action-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
        }}
        .action-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        }}
        .action-btn {{
            display: block;
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: bold;
            font-size: 16px;
            margin-top: 15px;
            transition: opacity 0.3s ease;
        }}
        .action-btn:hover {{
            opacity: 0.9;
        }}
        .action-icon {{
            font-size: 48px;
            margin-bottom: 10px;
        }}
        .footer {{
            text-align: center;
            color: white;
            margin-top: 40px;
            opacity: 0.8;
        }}
        @media (max-width: 768px) {{
            body {{ padding: 10px; }}
            .header h1 {{ font-size: 32px; }}
            .cards-grid {{ grid-template-columns: 1fr; }}
            .actions-grid {{ grid-template-columns: 1fr; }}
            .sensor-value {{ font-size: 36px; }}
        }}
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1>🌡️ Pico W Sensor Dashboard</h1>
            <p>DHT22 Temperature & Humidity Monitor</p>
            <p>IP: {ip_address} | Uptime: {uptime_hours:02d}:{uptime_minutes:02d} | Version: {current_version}</p>
        </div>

        <div class="cards-grid">
            <div class="card">
                <div class="card-header">
                    <div class="card-icon">🌡️</div>
                    <h2 class="card-title">Temperature</h2>
                </div>
                <div class="sensor-value">
                    {temp if temp is not None else "ERROR"}
                    <span class="sensor-unit">°C</span>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <div class="card-icon">💧</div>
                    <h2 class="card-title">Humidity</h2>
                </div>
                <div class="sensor-value">
                    {hum if hum is not None else "ERROR"}
                    <span class="sensor-unit">%</span>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <div class="card-icon">📊</div>
                    <h2 class="card-title">System Status</h2>
                </div>
                <div class="status-item">
                    <span class="status-label">WiFi</span>
                    <span class="status-value">
                        {wifi_status}
                        <span class="status-indicator" style="background-color: {wifi_color};"></span>
                    </span>
                </div>
                <div class="status-item">
                    <span class="status-label">Sensor</span>
                    <span class="status-value">
                        {"OK" if temp is not None else "ERROR"}
                        <span class="status-indicator" style="background-color: {'#28a745' if temp is not None else '#dc3545'};"></span>
                    </span>
                </div>
                <div class="status-item">
                    <span class="status-label">OTA</span>
                    <span class="status-value">
                        {"Enabled" if ota_updater else "Disabled"}
                        <span class="status-indicator" style="background-color: {'#28a745' if ota_updater else '#ffc107'};"></span>
                    </span>
                </div>
                <div class="status-item">
                    <span class="status-label">Updates</span>
                    <span class="status-value">
                        {update_status}
                        <span class="status-indicator" style="background-color: {update_color};"></span>
                    </span>
                </div>
            </div>
        </div>

        <div class="actions-grid">
            <div class="action-card">
                <div class="action-icon">🏥</div>
                <h3>System Health</h3>
                <p>Comprehensive system monitoring and diagnostics</p>
                <a href="/health" class="action-btn">View Health Dashboard</a>
            </div>

            <div class="action-card">
                <div class="action-icon">🔄</div>
                <h3>OTA Updates</h3>
                <p>Check for and manage firmware updates</p>
                <a href="/update/status" class="action-btn">Update Status</a>
            </div>

            <div class="action-card">
                <div class="action-icon">📊</div>
                <h3>Prometheus Metrics</h3>
                <p>Raw metrics data for monitoring systems</p>
                <a href="/metrics" class="action-btn">View Metrics</a>
            </div>

            <div class="action-card">
                <div class="action-icon">⚡</div>
                <h3>Quick Update</h3>
                <p>Check for and install firmware updates</p>
                <a href="/update" class="action-btn">Check Updates</a>
            </div>
        </div>

        <div class="footer">
            <p>🔧 Pico W DHT22 Sensor | Auto-refresh: 30 seconds</p>
            <p>📡 Professional IoT monitoring solution</p>
        </div>
    </div>
</body>
</html>"""
                cl.send(html)
            except Exception as e:
                # Fallback to simple text response if HTML generation fails
                endpoints_info = f"""Available endpoints:
{METRICS_ENDPOINT} - Prometheus metrics
/health - Health check
/update/status - Update status
/update - Trigger OTA update
"""
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n")
                cl.send(endpoints_info)

        else:
            # 404 for unknown endpoints
            cl.send("HTTP/1.0 404 Not Found\r\nContent-Type: text/plain\r\n\r\n")
            cl.send(f"Endpoint not found: {method} {path}")

        cl.close()

    except OSError as e:
        print("Socket error:", e)
        cl.close()
