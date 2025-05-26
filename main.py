import network
import socket
import time
import rp2
from secrets import secrets
from machine import Pin
import dht

# Wi-Fi Setup
ssid = secrets['ssid']
password = secrets['pw']
rp2.country('GB')  # or your 2-letter code

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
    print('Waiting for connection...')
    max_wait -= 1
    time.sleep(1)

if wlan.status() != 3:
    raise RuntimeError('Wi-Fi connection failed')
else:
    print('Connected, IP =', wlan.ifconfig()[0])

# DHT22 Sensor Setup
sensor = dht.DHT22(Pin(2))  # GPIO2

def read_dht22():
    try:
        sensor.measure()
        t = sensor.temperature()
        h = sensor.humidity()
        return round(t, 2), round(h, 2)
    except Exception as e:
        print("Sensor read failed:", e)
        return None, None

# HTTP Server (Prometheus-style)
def format_metrics(temp, hum):
    return (
        "# HELP pico_temperature_celsius Temperature in Celsius\n"
        "# TYPE pico_temperature_celsius gauge\n"
        f"pico_temperature_celsius {temp}\n"
        "# HELP pico_humidity_percent Humidity in Percent\n"
        "# TYPE pico_humidity_percent gauge\n"
        f"pico_humidity_percent {hum}\n"
    )

addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(addr)
s.listen(1)

print('Listening on http://%s/metrics' % wlan.ifconfig()[0])

while True:
    try:
        cl, addr = s.accept()
        print('Client connected from', addr)
        request = cl.recv(1024)
        request_line = request.decode().split('\r\n')[0]

        if 'GET /metrics' in request_line:
            temp, hum = read_dht22()
            if temp is not None:
                response = format_metrics(temp, hum)
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n')
                cl.send(response)
            else:
                cl.send('HTTP/1.0 500 Internal Server Error\r\n\r\n')
                cl.send("Sensor error")
        else:
            cl.send('HTTP/1.0 404 Not Found\r\n\r\n')

        cl.close()

    except OSError as e:
        print("Socket error:", e)
        cl.close()

