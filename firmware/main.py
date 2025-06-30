"""
Pico W Prometheus DHT22 Sensor Server

A MicroPython-based HTTP server for the Raspberry Pi Pico W that exposes
DHT22 sensor readings (temperature and humidity) as Prometheus-compatible metrics.

This module connects to WiFi, reads from a DHT22 sensor, and serves metrics
via an HTTP endpoint for Prometheus scraping.
"""

# BOOT PROTECTION: WiFi setup first, before any other imports
import network
import time
from secrets import secrets

# Initialize WiFi immediately for recovery access
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# BOOT PROTECTION: Try to import all modules with fallback to recovery mode
try:
    import socket
    import dht
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
        handle_logs_page,
    )

    print("BOOT: All modules loaded successfully")
    RECOVERY_MODE = False

except ImportError as e:
    print(f"BOOT FAILURE: Module import failed: {e}")
    print("ACTIVATING RECOVERY MODE...")
    RECOVERY_MODE = True

    # Execute recovery mode
    exec(open('recovery.py').read())
    # Recovery mode runs its own server loop, so we exit here
    exit()

except Exception as e:
    print(f"BOOT FAILURE: Unexpected error: {e}")
    print("ACTIVATING RECOVERY MODE...")
    RECOVERY_MODE = True

    # Execute recovery mode
    exec(open('recovery.py').read())
    # Recovery mode runs its own server loop, so we exit here
    exit()

# Record boot time using ticks for accurate uptime calculation
boot_ticks = time.ticks_ms()

# Simplified update tracking - no complex status
update_in_progress = False

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
        # Removed verbose sensor reading logs to save log space
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


def handle_update_request():
    """
    Handle OTA update request with immediate execution - minimal HTML with links.

    Returns:
        str: HTTP response for update request.
    """
    global update_in_progress

    if not ota_updater:
        log_warn("OTA update requested but OTA not enabled", "OTA")
        return "HTTP/1.0 503 Service Unavailable\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html><html><head><title>OTA Not Enabled</title></head><body><h1>OTA NOT ENABLED</h1><p>Over-the-air updates are disabled.</p><p><a href='/config'>Enable in configuration</a> | <a href='/'>Return home</a></p></body></html>"

    if update_in_progress:
        log_info("Update already in progress", "OTA")
        return "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html><html><head><title>Update In Progress</title></head><body><h1>UPDATE IN PROGRESS</h1><p>An update is already running.<br>Device will restart automatically when complete.</p><p><a href='/health?update=true'>Monitor progress</a></p></body></html>"

    try:
        log_info("Manual update requested", "OTA")

        # Check for available updates
        has_update, new_version, error_info = ota_updater.check_for_updates()

        if not has_update:
            if error_info == "REPO_NOT_FOUND":
                log_error("Repository not found", "OTA")
                return "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html><html><head><title>Repository Not Found</title></head><body><h1>REPOSITORY NOT FOUND</h1><p>The configured repository could not be found. Please check your repository settings.</p><p><a href='/config'>Update Configuration</a> | <a href='/'>Return home</a></p></body></html>"
            else:
                log_info("No updates available", "OTA")
                return "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html><html><head><title>No Updates</title></head><body><h1>NO UPDATES AVAILABLE</h1><p>Current version is up to date.</p><p><a href='/health'>View system status</a> | <a href='/'>Return home</a></p></body></html>"

        # Get current version for display
        current_version = ota_updater.get_current_version()

        # Set update in progress flag
        update_in_progress = True

        log_info(f"Starting immediate update: {current_version} -> {new_version}", "OTA")

        # Return minimal HTML response with links
        update_html = f"""<!DOCTYPE html><html><head><title>Update Started</title></head><body>
<h1>UPDATE STARTED SUCCESSFULLY</h1>

<h2>Update Details</h2>
<p><strong>Current Version:</strong> {current_version}<br>
<strong>Target Version:</strong> {new_version}<br>
<strong>Status:</strong> Downloading and applying update...</p>

<h2>Important</h2>
<p>- Device will restart automatically in 1-2 minutes<br>
- DO NOT power off the device during update<br>
- You may lose connection temporarily during restart</p>

<h2>Links</h2>
<p><a href="/health?update=true">Monitor progress</a> | <a href="/">Dashboard</a></p>
</body></html>"""

        # Start update in background (will happen after response is sent)
        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{update_html}"

    except Exception as e:
        update_in_progress = False
        log_error(f"Update request failed: {e}", "OTA")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html><html><head><title>Update Failed</title></head><body><h1>UPDATE FAILED</h1><p>Error: {e}</p><p><a href='/'>Return home</a></p></body></html>"


def handle_reboot_request():
    """
    Handle manual reboot request with confirmation page.

    Returns:
        str: HTTP response for reboot request.
    """
    try:
        log_info("Manual reboot requested", "SYSTEM")

        # Return confirmation page with delayed reboot
        reboot_html = """<!DOCTYPE html><html><head><title>Rebooting Device</title></head><body>
<h1>DEVICE REBOOT INITIATED</h1>

<h2>Reboot Status</h2>
<p><strong>Status:</strong> Device will restart in 3 seconds...<br>
<strong>Expected downtime:</strong> 10-15 seconds<br>
<strong>Reconnection:</strong> Device will reconnect to WiFi automatically</p>

<h2>Important</h2>
<p>• Device will be temporarily unavailable<br>
• All current connections will be lost<br>
• Refresh this page after 15 seconds to reconnect</p>

<h2>Links</h2>
<p><a href="/">Return to Dashboard</a> (available after reboot)</p>
</body></html>"""

        # Schedule reboot after response is sent
        import _thread
        def delayed_reboot():
            time.sleep(3)
            log_info("Executing manual reboot", "SYSTEM")
            import machine
            machine.reset()

        try:
            _thread.start_new_thread(delayed_reboot, ())
        except:
            # Fallback if threading not available
            pass

        return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n{reboot_html}"

    except Exception as e:
        log_error(f"Reboot request failed: {e}", "SYSTEM")
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html><html><head><title>Reboot Failed</title></head><body><h1>REBOOT FAILED</h1><p>Error: {e}</p><p><a href='/'>Return home</a></p></body></html>"


def perform_immediate_update():
    """
    Perform immediate OTA update with ultra-aggressive memory management.
    """
    global update_in_progress

    try:
        log_info("Starting immediate OTA update", "OTA")

        # Ultra-aggressive memory cleanup before OTA
        gc.collect()
        gc.collect()  # Double collection
        initial_mem = gc.mem_free()

        # Check for updates again (quick check)
        has_update, new_version, _ = ota_updater.check_for_updates()
        if not has_update:
            log_warn("No update available during immediate update", "OTA")
            update_in_progress = False
            return

        # Clear variables immediately
        has_update = None
        gc.collect()

        log_info("Starting staged download...", "OTA")

        # Ultra-aggressive cleanup before download
        gc.collect()
        gc.collect()
        download_mem = gc.mem_free()

        download_success = ota_updater.download_update(new_version, None)

        if not download_success:
            log_error("Staged download failed", "OTA")
            update_in_progress = False
            return

        # Clear download variables
        download_success = None
        gc.collect()

        log_info("Applying staged update...", "OTA")

        # Ultra-aggressive cleanup before applying
        gc.collect()
        gc.collect()
        apply_mem = gc.mem_free()

        # Apply the update
        apply_success = ota_updater.apply_update(new_version)

        if apply_success:
            log_info("Staged update completed, restarting in 2 seconds", "OTA")

            # Final cleanup before restart
            apply_success = None
            new_version = None
            gc.collect()

            time.sleep(2)

            # Device will restart here
            import machine
            machine.reset()
        else:
            log_error("Update application failed", "OTA")
            update_in_progress = False

    except Exception as e:
        log_error(f"Immediate update failed: {e}", "OTA")
        update_in_progress = False
        # Emergency cleanup
        gc.collect()


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

        # Removed verbose HTTP request logs to save log space

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
            response = handle_health_check(sensor_data, system_info, ota_updater, wlan, ssid, request_str)
            cl.send(response)

        elif method == "GET" and path == "/config":
            # Configuration page
            response = handle_config_page()
            cl.send(response)

        elif method == "POST" and path == "/config":
            # Configuration update
            response = handle_config_update(request, ota_updater)
            cl.send(response)

        elif method == "GET" and path == "/logs":
            # Logs page endpoint
            response = handle_logs_page(request)
            cl.send(response)

        elif method == "GET" and path == "/update":
            # Manual update trigger - immediate execution
            response = handle_update_request()
            cl.send(response)

            # If update was started, perform it after sending response
            if update_in_progress:
                perform_immediate_update()

        elif method == "GET" and path == "/reboot":
            # Manual reboot trigger
            response = handle_reboot_request()
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
            # Accept connections with timeout
            s.settimeout(1.0)  # 1 second timeout
            try:
                cl, addr = s.accept()
                # Removed verbose connection logs to save log space
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
