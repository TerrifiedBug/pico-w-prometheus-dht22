# pico-w-prometheus-dht22

A lightweight MicroPython-based HTTP server for the Raspberry Pi Pico W that exposes DHT22 sensor readings (temperature and humidity) as Prometheus-compatible metrics.

---

## 📦 Features

- 📡 Connects to Wi-Fi on boot
- 🌡️ Reads from a DHT22 sensor (temperature + humidity)
- 📊 Exposes `/metrics` HTTP endpoint in Prometheus exposition format
- 📈 Compatible with Prometheus + Grafana dashboards
- 🏠 Ideal for home room monitoring setups

---

## 🧰 Requirements

- Raspberry Pi Pico W
- DHT22 sensor
- MicroPython firmware (v1.20+)
- Optional: Prometheus + Grafana instance

---

## 📁 File Structure

```
.
├── main.py          # Wi-Fi + HTTP server + sensor reading
├── secrets.py       # Wi-Fi credentials
├── README.md        # This file
```

---

## 🔧 Setup Instructions

### 1. Flash MicroPython to Pico W

Download the `.uf2` firmware from the [official site](https://micropython.org/download/rp2-pico-w/) and drag it onto the `RPI-RP2` volume in bootloader mode.

### 2. Upload Project Files

Use **Thonny** or `mpremote` to copy these files to the Pico:

#### `secrets.py`

```python
secrets = {
    'ssid': 'YourWiFiName',
    'pw': 'YourWiFiPassword'
}
```

#### `main.py`

> Contains full server logic. On boot, it connects to Wi-Fi and starts listening on port `80`.

### 3. Reboot the Pico

Once connected, it will print its IP address via REPL.

---

## 📡 Metrics Output

Visit `http://<pico-ip>/metrics` to see:

```
# HELP pico_temperature_celsius Temperature in Celsius
# TYPE pico_temperature_celsius gauge
pico_temperature_celsius 21.8
# HELP pico_humidity_percent Humidity in Percent
# TYPE pico_humidity_percent gauge
pico_humidity_percent 55.4
```

---

## 📈 Prometheus Configuration

Update your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "pico_sensors"
    metrics_path: /metrics
    static_configs:
      - targets:
          - "10.1.1.161:80"
        labels:
          location: kitchen
      - targets:
          - "10.1.1.162:80"
        labels:
          location: bedroom
```

Restart Prometheus after editing.

---

## 📊 Grafana Dashboard (Optional)

- Add Prometheus as a data source
- Create a new dashboard with a time-series panel
- Use query:
  ```promql
  pico_temperature_celsius
  ```
- Use `{{location}}` as the legend for multi-room graphs

---

## 📝 License

MIT — free for personal or commercial use.

---

## 🙋‍♂️ Credits

Created by TerrifiedBug
Inspired by [Prometheus-style embedded metrics exporters](http://www.d3noob.org/2022/10/using-raspberry-pi-pico-with-prometheus.html)
