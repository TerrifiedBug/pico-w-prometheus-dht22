# Pico W Prometheus DHT22 Sensor

A lightweight MicroPython-based HTTP server for the Raspberry Pi Pico W that exposes DHT22 sensor readings (temperature and humidity) as Prometheus-compatible metrics with Over-The-Air (OTA) update capabilities.

---

## 📦 Features

- 📡 **Wi-Fi Connectivity**: Automatic connection on boot with configurable settings
- 🌡️ **DHT22 Sensor**: Reads temperature and humidity with error handling
- 📊 **Prometheus Metrics**: Standard exposition format at `/metrics` endpoint with dynamic labels
- 📈 **Monitoring Ready**: Compatible with Prometheus + Grafana dashboards
- 🔄 **OTA Updates**: Remote updates via GitHub releases with safety features
- 🏥 **Health Monitoring**: Multiple endpoints for system status and diagnostics
- ⚙️ **Configurable**: Centralized configuration via `config.py` + web interface
- 🏷️ **Dynamic Labels**: Configure sensor location and device name via web interface
- 🛡️ **Robust**: Backup/restore system and automatic rollback on failures
- 🏠 **IoT Ready**: Perfect for distributed sensor deployments

---

## 🧰 Requirements

### Hardware

- Raspberry Pi Pico W
- DHT22 temperature/humidity sensor
- Breadboard and jumper wires (or custom PCB)

### Software

- MicroPython firmware (v1.20+)
- Optional: Prometheus + Grafana for monitoring
- Git for version control and releases

---

## 📁 Project Structure

```
pico-w-prometheus-dht22/
├── main.py                           # Main application entry point
├── ota_updater.py                    # OTA update functionality
├── config.py                         # Configuration settings
├── secrets.py.example                # WiFi credentials template
├── version.txt                       # Current firmware version
├── .gitignore                        # Git ignore rules
├── README.md                         # This documentation
├── configs/                          # External configuration files
│   ├── prometheus.yml                # Prometheus scrape config
│   └── grafana-dashboard.json        # Grafana dashboard template
├── .github/                          # GitHub Actions workflows
    └── workflows/
        └── release.yml               # Automated release creation
```

---

## 🔧 Setup Instructions

### 1. Flash MicroPython to Pico W

1. Download the latest `.uf2` firmware from [micropython.org](https://micropython.org/download/rp2-pico-w/)
2. Hold the BOOTSEL button while connecting USB to enter bootloader mode
3. Drag the `.uf2` file to the `RPI-RP2` volume
4. The Pico will reboot automatically

### 2. Prepare Project Files

Clone this repository:

```bash
git clone https://github.com/TerrifiedBug/pico-w-prometheus-dht22.git
cd pico-w-prometheus-dht22
```

Create your WiFi credentials file:

```bash
cp secrets.py.example secrets.py
```

Edit `secrets.py` with your WiFi details:

```python
secrets = {
    'ssid': 'YourWiFiName',
    'pw': 'YourWiFiPassword'
}
```

### 3. Configure the Project

Edit `config.py` to customize settings:

```python
# Sensor configuration
SENSOR_CONFIG = {
    "pin": 2,  # GPIO pin for DHT22 sensor
    "read_interval": 30,
}

# OTA configuration
OTA_CONFIG = {
    "enabled": True,
    "github_repo": {
        "owner": "yourusername",  # Replace with your GitHub username
        "name": "pico-w-prometheus-dht22",
        "branch": "main",
    },
}
```

### 4. Upload Files to Pico W

Using **Thonny IDE** (recommended for beginners):

1. Open Thonny and connect to your Pico W
2. Upload these files to the Pico's root directory:
   - `main.py`
   - `ota_updater.py`
   - `config.py`
   - `secrets.py`
   - `version.txt`

Using **mpremote** (command line):

```bash
mpremote cp main.py ota_updater.py config.py secrets.py version.txt :
```

### 5. Hardware Connections

Connect the DHT22 sensor:

- **VCC** → 3.3V (Pin 36)
- **GND** → Ground (Pin 38)
- **DATA** → GPIO 2 (Pin 4) - or change in `config.py`

### 6. Start the System

1. Reset the Pico W or run `main.py` in Thonny
2. Monitor the REPL output for the assigned IP address
3. Test the connection: `http://<pico-ip>/health`

---

## 📡 Available Endpoints

| Endpoint         | Method | Description                          |
| ---------------- | ------ | ------------------------------------ |
| `/`              | GET    | List all available endpoints         |
| `/metrics`       | GET    | Prometheus-formatted sensor metrics  |
| `/health`        | GET    | System health check and version info |
| `/config`        | GET    | Device configuration web interface   |
| `/config`        | POST   | Update device configuration          |
| `/update/status` | GET    | Current OTA update status            |
| `/update`        | GET    | Trigger manual OTA update            |

### Example Metrics Output

Visit `http://<pico-ip>/metrics`:

```prometheus
# HELP pico_temperature_celsius Temperature in Celsius
# TYPE pico_temperature_celsius gauge
pico_temperature_celsius 21.8

# HELP pico_humidity_percent Humidity in Percent
# TYPE pico_humidity_percent gauge
pico_humidity_percent 55.4

# HELP pico_sensor_status Sensor health status (1=OK, 0=FAIL)
# TYPE pico_sensor_status gauge
pico_sensor_status 1

# HELP pico_ota_status OTA system status (1=enabled, 0=disabled)
# TYPE pico_ota_status gauge
pico_ota_status 1

# HELP pico_version_info Current firmware version
# TYPE pico_version_info gauge
pico_version_info{version="v1.0.0"} 1

# HELP pico_uptime_seconds Approximate uptime in seconds
# TYPE pico_uptime_seconds counter
pico_uptime_seconds 3600
```

---

## 🏷️ Dynamic Configuration

### Overview

The dynamic configuration feature allows you to set sensor location and device name via a web interface, eliminating the need to restart Prometheus when sensors are moved or renamed.

### Configuration Web Interface

Visit `http://<pico-ip>/config` to access the configuration page:

- **Location**: Set the physical location (e.g., "bedroom", "kitchen", "living-room")
- **Device Name**: Set a unique device identifier (e.g., "sensor-01", "temp-sensor")
- **Description**: Optional description for documentation purposes

### Dynamic Prometheus Labels

With dynamic configuration, metrics automatically include location and device labels:

```prometheus
# Before (static metrics)
pico_temperature_celsius 21.8

# After (dynamic labels)
pico_temperature_celsius{location="bedroom",device="sensor-01"} 21.8
pico_humidity_percent{location="bedroom",device="sensor-01"} 55.4
pico_sensor_status{location="bedroom",device="sensor-01"} 1
```

### Benefits

- **No Prometheus restarts**: Changes take effect immediately
- **Easy sensor relocation**: Update location via web interface
- **Multiple sensors**: Each device has unique identity
- **Flexible labeling**: Use location and device labels in queries

### Usage Example

1. **Initial Setup**: Visit `/config` and set location to "kitchen", device to "sensor-01"
2. **Move Sensor**: Physically move sensor to bedroom
3. **Update Config**: Visit `/config` and change location to "bedroom"
4. **Immediate Effect**: Prometheus metrics now show `location="bedroom"`

### Prometheus Configuration

With dynamic labels, you can simplify your Prometheus configuration:

```yaml
# Simplified - no static labels needed
scrape_configs:
  - job_name: "pico_sensors"
    static_configs:
      - targets:
          - "192.168.1.100:80"
          - "192.168.1.101:80"
          - "192.168.1.102:80"
    # Labels now come from device metrics automatically
```

---

## 📈 Prometheus Integration

### Configuration

Add to your `prometheus.yml`:

```yaml
global:
  scrape_interval: 30s

scrape_configs:
  - job_name: "pico_sensors"
    metrics_path: /metrics
    scrape_interval: 30s
    static_configs:
      - targets:
          - "192.168.1.100:80" # Replace with your Pico's IP
        labels:
          location: "kitchen"
          device: "pico-w-001"
      - targets:
          - "192.168.1.101:80"
        labels:
          location: "bedroom"
          device: "pico-w-002"
```

### Useful Queries

```promql
# Current temperature by location
pico_temperature_celsius

# Humidity levels
pico_humidity_percent

# Device health status
pico_sensor_status

# Devices that are offline
up{job="pico_sensors"} == 0
```

---

## 📊 Grafana Dashboard

Import the provided dashboard from `configs/grafana-dashboard.json` or create panels with these queries:

![image](https://github.com/user-attachments/assets/94b9de46-e617-4d34-aa95-315b0f37536a)

### Temperature Panel

- **Query**: `pico_temperature_celsius`
- **Legend**: `{{location}} - {{device}}`
- **Unit**: Celsius (°C)

### Humidity Panel

- **Query**: `pico_humidity_percent`
- **Legend**: `{{location}} - {{device}}`
- **Unit**: Percent (%)

### Device Status Panel

- **Query**: `pico_sensor_status`
- **Type**: Stat panel
- **Thresholds**: 0 = Red, 1 = Green

---

## 🔄 Over-The-Air (OTA) Updates

### How It Works

1. **Version Tracking**: Current version stored in `version.txt`
2. **GitHub Integration**: Automatically checks GitHub releases
3. **Safe Downloads**: Files downloaded to temporary directory first
4. **Atomic Updates**: All files replaced simultaneously
5. **Backup System**: Current files backed up before update
6. **Auto Rollback**: Restores backup if update fails

### Creating Releases

1. **Make Changes**: Edit your code and test locally
2. **Commit Changes**:
   ```bash
   git add .
   git commit -m "Add new feature"
   git push origin main
   ```
3. **Create Release**:
   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```
4. **Automatic Release**: GitHub Actions creates the release
5. **Device Updates**: Pico W devices can now update to v1.0.1

### Manual Update Process

1. **Check Status**: Visit `http://<pico-ip>/update/status`
2. **Trigger Update**: Visit `http://<pico-ip>/update`
3. **Monitor Progress**: Device will restart automatically
4. **Verify Update**: Check `http://<pico-ip>/health` for new version

### Safety Features

- ✅ **Backup System**: Files backed up before update
- ✅ **Atomic Updates**: All-or-nothing file replacement
- ✅ **Rollback**: Automatic restore on failure
- ✅ **Health Checks**: System status verification
- ✅ **Network Resilience**: Handles connection failures gracefully

---

## 🛠️ Troubleshooting

### Common Issues

**WiFi Connection Failed**

- Check SSID and password in `secrets.py`
- Verify 2.4GHz network (Pico W doesn't support 5GHz)
- Check signal strength

**Sensor Reading Errors**

- Verify DHT22 wiring connections
- Check GPIO pin configuration in `config.py`
- Ensure adequate power supply (3.3V)

**OTA Update Failures**

- Check internet connectivity
- Verify GitHub repository is public
- Ensure sufficient storage space on Pico W

**Prometheus Not Scraping**

- Verify Pico W IP address in `prometheus.yml`
- Check firewall settings
- Confirm `/metrics` endpoint is accessible

### Debug Information

Enable debug output by monitoring the REPL console during operation. Key information includes:

- WiFi connection status and IP address
- Sensor reading success/failure
- HTTP request handling
- OTA update progress

---

## 🔧 Advanced Configuration

### Custom Metric Names

Edit `config.py` to customize metric names:

```python
METRIC_NAMES = {
    "temperature": "room_temperature_celsius",
    "humidity": "room_humidity_percent",
}
```

### Network Settings

Configure static IP (optional):

```python
# In main.py, uncomment and modify:
wlan.ifconfig(('192.168.1.100','255.255.255.0','192.168.1.1','8.8.8.8'))
```

### Update File Selection

Choose which files to update via OTA:

```python
OTA_CONFIG = {
    "update_files": [
        "main.py",
        "config.py",
        "ota_updater.py",
        # Add other files as needed
    ],
}
```

---

## 📚 Documentation

- **[OTA Implementation Guide](internal-docs/OTA_IMPLEMENTATION_GUIDE.md)**: Detailed technical documentation
- **[Prometheus Configuration](configs/prometheus.yml)**: Example scrape configuration
- **[Grafana Dashboard](configs/grafana-dashboard.json)**: Pre-built dashboard template

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and test thoroughly
4. Commit with clear messages: `git commit -m "Add feature description"`
5. Push to your fork: `git push origin feature-name`
6. Create a Pull Request

---

## 📝 License

MIT License - free for personal and commercial use.

---

## 🙋‍♂️ Credits

Created by **TerrifiedBug**

Inspired by Prometheus-style embedded metrics exporters and the need for reliable IoT sensor monitoring with remote update capabilities.

---

## ⭐ Support

If this project helps you, please consider:

- ⭐ Starring the repository
- 🐛 Reporting issues
- 💡 Suggesting improvements
- 📖 Contributing to documentation

For support, please open an issue on GitHub with:

- Your hardware setup
- MicroPython version
- Error messages or logs
- Steps to reproduce the problem
