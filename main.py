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
    Format temperature and humidity readings as Prometheus metrics.

    Args:
        temperature (float): Temperature reading in Celsius.
        humidity (float): Humidity reading as a percentage.

    Returns:
        str: Formatted Prometheus metrics string with HELP and TYPE comments.
    """
    return (
        f"# HELP {METRIC_NAMES['temperature']} Temperature in Celsius\n"
        f"# TYPE {METRIC_NAMES['temperature']} gauge\n"
        f"{METRIC_NAMES['temperature']} {temperature}\n"
        f"# HELP {METRIC_NAMES['humidity']} Humidity in Percent\n"
        f"# TYPE {METRIC_NAMES['humidity']} gauge\n"
        f"{METRIC_NAMES['humidity']} {humidity}\n"
    )


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

        if f"GET {METRICS_ENDPOINT}" in request_line:
            temp, hum = read_dht22()
            if temp is not None:
                response = format_metrics(temp, hum)
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n")
                cl.send(response)
            else:
                cl.send("HTTP/1.0 500 Internal Server Error\r\n\r\n")
                cl.send("Sensor error")
        else:
            cl.send("HTTP/1.0 404 Not Found\r\n\r\n")

        cl.close()

    except OSError as e:
        print("Socket error:", e)
        cl.close()
