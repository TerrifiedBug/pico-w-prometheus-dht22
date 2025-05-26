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

# Record boot time for accurate uptime calculation
boot_time = time.time()

# Wi-Fi Setup
ssid = secrets["ssid"]
password = secrets["pw"]
rp2.country(WIFI_CONFIG["country_code"])

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(ssid, password)

# Optional: set static IP (adjust as needed)
# wlan.ifconfig(('10.1.1.161','255.255.255.0','10.1.1.1','8.8.8.8'))

print("Connecting to Wi-Fi...")
max_wait = 10
while max_wait > 0:
    if wlan.status() >= 3:
        break
    print("Waiting for connection...")
    max_wait -= 1
    time.sleep(1)

if wlan.status() != 3:
    raise RuntimeError("Wi-Fi connection failed")
else:
    print("Connected, IP =", wlan.ifconfig()[0])

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

    # System uptime (actual time since boot)
    uptime_seconds = time.time() - boot_time
    metrics.extend([
        "# HELP pico_uptime_seconds Actual uptime in seconds since boot",
        "# TYPE pico_uptime_seconds counter",
        f"pico_uptime_seconds {uptime_seconds:.0f}",
    ])


    return "\n".join(metrics) + "\n"


def handle_update_request():
    """
    Handle OTA update request.

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
    Handle update status request.

    Returns:
        str: HTTP response with update status information.
    """
    if not ota_updater:
        status = "OTA disabled"
    else:
        try:
            status_info = ota_updater.get_update_status()
            status = f"Current version: {status_info['current_version']}\n"
            status += f"OTA enabled: {status_info['ota_enabled']}\n"
            status += f"Auto check: {status_info['auto_check']}\n"
            status += f"Repository: {status_info['repo']}\n"
            status += f"Branch: {status_info['branch']}\n"
            status += f"Update files: {', '.join(status_info['update_files'])}"
        except Exception as e:
            status = f"Status error: {e}"

    return f"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n{status}"


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

        health_info = f"Sensor: {sensor_status}\nOTA: {ota_status}\nVersion: "
        if ota_updater:
            health_info += ota_updater.get_current_version()
        else:
            health_info += "unknown"

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
            # OTA update endpoint - exact match only
            response = handle_update_request()
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
