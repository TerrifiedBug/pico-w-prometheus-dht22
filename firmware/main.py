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
import gc

from config import (
    METRIC_NAMES,
    METRICS_ENDPOINT,
    SENSOR_CONFIG,
    SERVER_CONFIG,
    WIFI_CONFIG,
)
from device_config import get_config_for_metrics
from logger import log_info, log_warn, log_error, log_debug

# Import web interface functions
from web_interface import (
    handle_root_page,
    handle_health_check,
    handle_config_page,
    handle_config_update,
    handle_update_status,
    handle_logs_page,
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


def get_system_info():
    """Get system information for web interface."""
    # WiFi information
    wifi_status = "Connected" if wlan.isconnected() else "Disconnected"
    wifi_class = "status-ok" if wlan.isconnected() else "status-error"
    ip_address = wlan.ifconfig()[0] if wlan.isconnected() else "N/A"

    # System uptime
    uptime_ms = time.ticks_diff(time.ticks_ms(), boot_ticks)
    if uptime_ms < 0:
        uptime_ms = uptime_ms + (1 << 30)
    uptime_seconds = max(0, uptime_ms // 1000)
    uptime_hours = uptime_seconds // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60
    uptime_days = uptime_hours // 24
    uptime_hours = uptime_hours % 24

    # Memory information
    gc.collect()
    free_memory = gc.mem_free()
    memory_mb = round(free_memory / 1024, 1)
    memory_class = "status-ok" if free_memory > 100000 else "status-warn" if free_memory > 50000 else "status-error"

    return {
        "wifi": (wifi_status, wifi_class, ip_address),
        "uptime": (uptime_hours, uptime_minutes),
        "uptime_detailed": (uptime_days, uptime_hours, uptime_minutes),
        "memory": memory_mb,
        "memory_detailed": (free_memory, memory_mb, memory_class),
    }


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
    Perform the scheduled OTA update with progress tracking and memory optimization.
    """
    try:
        log_info(f"Starting scheduled update to version {pending_update['version']}", "OTA")

        # Update status: Starting download
        pending_update["status"] = "downloading"
        pending_update["progress"] = 25
        pending_update["message"] = "Downloading update files..."

        # CRITICAL: Force aggressive memory cleanup before OTA
        log_info("Preparing for OTA: freeing memory...", "OTA")
        gc.collect()
        initial_mem = gc.mem_free()
        log_info(f"Memory before OTA: {initial_mem} bytes", "OTA")

        # Check for updates again (quick check)
        has_update, new_version, _ = ota_updater.check_for_updates()
        if not has_update:
            log_warn("No update available during scheduled update", "OTA")
            pending_update["scheduled"] = False
            pending_update["status"] = "idle"
            return

        # Update status: Downloading files
        log_info("Downloading update files...", "OTA")

        # Force another garbage collection before download
        gc.collect()
        download_mem = gc.mem_free()
        log_info(f"Memory before download: {download_mem} bytes", "OTA")

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

        # Force garbage collection before applying
        gc.collect()
        apply_mem = gc.mem_free()
        log_info(f"Memory before apply: {apply_mem} bytes", "OTA")

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

        if '?' in path:
            path = path.split('?')[0]

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
            sensor_data = read_dht22()
            system_info = get_system_info()
            response = handle_health_check(sensor_data, system_info, ota_updater, wlan, ssid)
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
            response = handle_update_status(ota_updater, pending_update)
            cl.send(response)

        elif method == "GET" and path == "/update":
            # Manual update trigger
            response = handle_update_request_delayed()
            cl.send(response)

        elif method == "GET" and path == "/":
            # Root endpoint - dashboard interface
            sensor_data = read_dht22()
            system_info = get_system_info()
            response = handle_root_page(sensor_data, system_info, ota_updater)
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
