# pico-w-prometheus-dht22

A lightweight MicroPython-based HTTP server for the Raspberry Pi Pico W that exposes DHT22 sensor readings (temperature and humidity) as Prometheus-compatible metrics.

---

## 📦 Features

- 📡 Connects to Wi-Fi on boot
- 🌡️ Reads from a DHT22 sensor (temperature + humidity)
- 📊 Exposes `/metrics` HTTP endpoint in Prometheus exposition format
- 📈 Compatible with Prometheus + Grafana dashboards
- 🔄 **Over-The-Air (OTA) updates** via GitHub releases
- 🏥 Health check and status endpoints
- ⚙️ Configurable settings via `config.py`
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
├── config.py        # Config file
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

## 🔄 Over-The-Air (OTA) Updates

This project supports automatic updates directly from GitHub releases, allowing you to update your Pico W remotely without physical access.

### 🚀 How OTA Works

1. **Version Tracking**: Current version stored in `version.txt`
2. **GitHub Integration**: Checks GitHub releases for newer versions
3. **Automatic Download**: Downloads updated files from GitHub
4. **Safe Updates**: Backs up current files before updating
5. **Rollback**: Automatically restores backup if update fails

### 📋 Available Endpoints

- `http://<pico-ip>/metrics` - Prometheus metrics
- `http://<pico-ip>/health` - Health check and version info
- `http://<pico-ip>/update/status` - Current update status
- `http://<pico-ip>/update` - Trigger manual update
- `http://<pico-ip>/` - List all available endpoints

### ⚙️ OTA Configuration

Edit `config.py` to configure OTA settings:

```python
OTA_CONFIG = {
    "enabled": True,
    "auto_check": True,
    "github_repo": {
        "owner": "yourusername",  # Your GitHub username
        "name": "pico-w-prometheus-dht22",
        "branch": "main",
    },
    "update_files": ["main.py", "config.py", "ota_updater.py"],
}
```

### 🏷️ Creating Releases

1. **Make your changes** and commit to GitHub
2. **Create a tag**: `git tag v1.0.1`
3. **Push the tag**: `git push origin v1.0.1`
4. **GitHub Actions** will automatically create a release
5. **Pico W devices** will detect and can update to the new version

### 🔧 Manual Update Process

1. Visit `http://<pico-ip>/update/status` to check current version
2. Visit `http://<pico-ip>/update` to trigger update
3. Device will download, apply update, and restart automatically
4. Check `http://<pico-ip>/health` to verify new version

### 🛡️ Safety Features

- **Backup System**: Current files backed up before update
- **Atomic Updates**: All files downloaded before any are replaced
- **Rollback**: Automatic restore if update fails
- **Health Checks**: Verify system status after updates

---

## 🙋‍♂️ Credits

Created by TerrifiedBug

Inspired by [Prometheus-style embedded metrics exporters](http://www.d3noob.org/2022/10/using-raspberry-pi-pico-with-prometheus.html)
