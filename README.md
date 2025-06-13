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
- 🔧 **Enhanced OTA Config**: Configure OTA settings via web interface
- 🛡️ **Robust**: Backup/restore system and automatic rollback on failures
- 🏠 **IoT Ready**: Perfect for distributed sensor deployments

---

## 📁 Project Structure

```
pico-w-prometheus-dht22/
├── firmware/                         # Deployable firmware files
│   ├── main.py                       # Main application entry point
│   ├── ota_updater.py               # OTA update functionality
│   ├── config.py                    # Configuration settings
│   ├── device_config.py             # Device configuration management
│   ├── secrets.py.example           # WiFi credentials template
│   └── version.txt                  # Current firmware version
├── configs/                         # External configuration files
│   ├── prometheus.yml               # Prometheus scrape config
│   └── grafana-dashboard.json       # Grafana dashboard template
├── .github/                        # GitHub Actions workflows
│   └── workflows/
│       └── release.yml             # Automated release creation
└── .gitignore                      # Git ignore rules
```

---

## 🚀 Quick Start

### 1. Download Firmware

Download the latest firmware package from the [Releases](https://github.com/TerrifiedBug/pico-w-prometheus-dht22/releases) page.

### 2. Flash MicroPython

1. Download MicroPython firmware from [micropython.org](https://micropython.org/download/rp2-pico-w/)
2. Hold BOOTSEL button while connecting USB
3. Copy the `.uf2` file to the `RPI-RP2` drive

### 3. Configure WiFi Credentials

**IMPORTANT**: You must configure WiFi credentials before uploading firmware.

1. Extract the firmware package to your computer
2. Copy `secrets.py.example` to `secrets.py`
3. Edit `secrets.py` with your WiFi credentials:
   ```python
   secrets = {
       "ssid": "YourWiFiNetworkName",
       "pw": "YourWiFiPassword"
   }
   ```

### 4. Upload Firmware

Upload all files (including your configured `secrets.py`) to your Pico W:

**Using Thonny IDE:**

1. Connect to your Pico W
2. Upload ALL files from the extracted firmware package to device root directory
3. Ensure `secrets.py` (with your credentials) is uploaded
4. Restart your Pico W

**Using mpremote:**

```bash
# From the extracted firmware directory
mpremote cp *.py version.txt :
mpremote exec "import main"
```

**⚠️ Security Notes:**

- `secrets.py` is never updated by OTA (your credentials stay safe)
- Keep a backup copy of your `secrets.py` file
- If you change WiFi networks, manually update `secrets.py` on the device

### 4. Configure Device

1. Connect to your device's IP address
2. Visit `/config` to configure:
   - **Device Settings**: Location, name, description
   - **OTA Settings**: Enable/disable updates, update interval, GitHub repo

---

## 📡 Available Endpoints

| Endpoint         | Method | Description                          |
| ---------------- | ------ | ------------------------------------ |
| `/`              | GET    | List all available endpoints         |
| `/metrics`       | GET    | Prometheus-formatted sensor metrics  |
| `/health`        | GET    | System health check and version info |
| `/config`        | GET    | Device & OTA configuration interface |
| `/config`        | POST   | Update device & OTA configuration    |
| `/update/status` | GET    | Current OTA update status            |
| `/update`        | GET    | Trigger manual OTA update            |

---

## 🏷️ Dynamic Configuration

### Device Configuration

- **Location**: Physical location (e.g., "bedroom", "kitchen")
- **Device Name**: Unique identifier (e.g., "sensor-01")
- **Description**: Optional description for documentation

### OTA Configuration

- **Enable/Disable OTA**: Toggle OTA functionality
- **Auto Updates**: Enable automatic update checking
- **Update Interval**: How often to check for updates (hours)
- **GitHub Repository**: Configure source repository and branch

### Dynamic Prometheus Labels

Metrics automatically include location and device labels:

```prometheus
pico_temperature_celsius{location="bedroom",device="sensor-01"} 21.8
pico_humidity_percent{location="bedroom",device="sensor-01"} 55.4
pico_sensor_status{location="bedroom",device="sensor-01"} 1
```

---

## 📈 Prometheus Integration

### Simplified Configuration

With dynamic labels, your Prometheus configuration becomes simpler:

```yaml
scrape_configs:
  - job_name: "pico_sensors"
    static_configs:
      - targets:
          - "192.168.1.100:80"
          - "192.168.1.101:80"
          - "192.168.1.102:80"
    # Labels now come from device metrics automatically
```

### Useful Queries

```promql
# Temperature by location
pico_temperature_celsius{location="bedroom"}

# All sensors in kitchen
{location="kitchen"}

# Device health status
pico_sensor_status == 0  # Unhealthy sensors
```

---

## 🔄 OTA Updates

### Automatic Updates

- Configure via web interface at `/config`
- Set update interval and GitHub repository
- Enable/disable as needed per device

### Manual Updates

1. Visit `/update/status` to check current status
2. Visit `/update` to trigger immediate update
3. Device will restart automatically after update

### Development vs Production

- **Production**: Uses `main` branch with stable releases (`v1.0.0`)
- **Development**: Uses `dev` branch with development releases (`dev-1.0.0`)

---

## 🛠️ Development

### Project Structure

- **firmware/**: Contains all deployable code
- **configs/**: External monitoring configurations
- **docs/**: Documentation files
- **tests/**: Test files and utilities

### Creating Releases

1. Make changes in appropriate branch (`main` or `dev`)
2. Commit and push changes
3. Create tag: `git tag v1.0.1` (or `dev-1.0.1` for dev)
4. Push tag: `git push origin v1.0.1`
5. GitHub Actions automatically creates release with firmware package

### Testing

```bash
cd tests/
python3 test_config.py
```

---

## 📚 Documentation

- **[Detailed Documentation](docs/README.md)**: Complete setup and usage guide
- **[Implementation Details](docs/DYNAMIC_CONFIG_IMPLEMENTATION.md)**: Technical implementation details
- **[Memory Bank](memory-bank/)**: Project knowledge base and patterns

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature-name`
3. Make changes in `firmware/` directory
4. Test thoroughly
5. Create Pull Request

---

## 📝 License

MIT License - free for personal and commercial use.

---

## 🙋‍♂️ Support

For support, please open an issue on GitHub with:

- Hardware setup details
- MicroPython version
- Error messages or logs
- Steps to reproduce the problem

---

**Created by TerrifiedBug** - Inspired by the need for reliable IoT sensor monitoring with flexible configuration and remote update capabilities.
