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

    # Handle potential negative values from tick wraparound
    if uptime_ms < 0:
        # If negative, likely due to tick counter wraparound (every ~12.4 days)
        # Calculate using the wraparound period (2^30 ms for MicroPython)
        uptime_ms = uptime_ms + (1 << 30)

    uptime_seconds = max(0, uptime_ms // 1000)  # Ensure non-negative
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
===================

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
            # Root endpoint - show available endpoints
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
