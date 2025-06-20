# Pico W Prometheus DHT22 Sensor

A simple temperature and humidity monitoring system using a Raspberry Pi Pico W and DHT22 sensor that exposes metrics for Prometheus monitoring.

## What It Does

- **Measures temperature and humidity** using a DHT22 sensor
- **Exposes metrics** in Prometheus format for monitoring dashboards
- **Web interface** for device status and configuration
- **Over-the-air updates** for easy firmware management
- **WiFi connectivity** for remote monitoring

## Quick Start

### Hardware Setup

1. Connect DHT22 sensor to GPIO pin 15 on your Pico W
2. Power the Pico W via USB

### Software Setup

1. Flash MicroPython to your Pico W
2. Copy all files from the `firmware/` folder to your Pico W
3. Create `secrets.py` with your WiFi credentials:
   ```python
   secrets = {
       "ssid": "YourWiFiName",
       "pw": "YourWiFiPassword"
   }
   ```
4. Reset the device - it will connect to WiFi and start serving metrics

## Using the Device

### Web Interface

Once connected, visit your device's IP address in a web browser:

- **Dashboard** (`/`) - Overview of sensor status and system info
- **Health Check** (`/health`) - Detailed system status
- **Configuration** (`/config`) - Change device settings
- **Logs** (`/logs`) - View system logs
- **Updates** (`/update`) - Update firmware over-the-air

### Prometheus Metrics

Add your device to Prometheus configuration:

```yaml
scrape_configs:
  - job_name: "pico-sensors"
    static_configs:
      - targets: ["192.168.1.100:80"] # Replace with your device IP
```

Metrics available at `/metrics`:

- `temperature_celsius` - Temperature reading
- `humidity_percent` - Humidity reading
- `pico_sensor_status` - Sensor health (1=OK, 0=FAIL)
- `pico_uptime_seconds` - Device uptime
- `pico_version_info` - Firmware version

## Configuration

### Device Settings

Use the web interface (`/config`) to configure:

- **Device name and location** - For metric labels
- **OTA update settings** - Enable/disable automatic updates
- **Update repository** - GitHub repo for firmware updates

### WiFi Settings

Edit `secrets.py` to change WiFi credentials, then restart the device.

## Monitoring Setup

### Grafana Dashboard

Import the included dashboard from `configs/grafana-dashboard.json` for:

- Temperature and humidity graphs
- Device status monitoring
- System health metrics

### Prometheus Configuration

Use the sample config in `configs/prometheus.yml` as a starting point.

## Firmware Updates

### Automatic Updates

- Enable in device configuration (`/config`)
- Device checks for updates periodically
- Updates happen automatically when available

### Manual Updates

1. Visit `/update` on your device
2. Confirm the update
3. Device will restart with new firmware
4. Check `/health` to confirm new version

## Troubleshooting

### Device Not Connecting

- Check WiFi credentials in `secrets.py`
- Ensure WiFi network is 2.4GHz (Pico W doesn't support 5GHz)
- Check device logs at `/logs`

### Sensor Not Working

- Verify DHT22 is connected to GPIO pin 15
- Check sensor wiring (VCC, GND, Data)
- View sensor status at `/health`

### Update Issues

- Ensure device has internet access
- Check logs at `/logs` for error details
- Updates require ~150KB free memory

## Hardware Requirements

- **Raspberry Pi Pico W** - WiFi-enabled microcontroller
- **DHT22 sensor** - Temperature and humidity sensor
- **Jumper wires** - For connections
- **Breadboard** (optional) - For prototyping

## Wiring Diagram

```
DHT22 Sensor    Pico W
VCC       →     3V3 (Pin 36)
GND       →     GND (Pin 38)
Data      →     GPIO 15 (Pin 20)
```

## Support

For issues or questions:

1. Check the logs at `/logs` on your device
2. Review the troubleshooting section above
3. Check the GitHub issues page

## License

This project is open source. See the repository for license details.
