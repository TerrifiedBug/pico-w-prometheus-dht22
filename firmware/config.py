"""
Configuration settings for Pico W Prometheus DHT22 sensor project

Provides base configuration for sensor, server, WiFi, and metrics.
Dynamic OTA configuration is handled by device_config.py.
"""

# =============================================================================
# SENSOR CONFIGURATION
# =============================================================================

SENSOR_CONFIG = {
    "pin": 2,  # GPIO pin for DHT22 sensor
    "read_interval": 30,  # Seconds between sensor readings
}

# =============================================================================
# SERVER CONFIGURATION
# =============================================================================

SERVER_CONFIG = {
    "host": "0.0.0.0",  # Listen on all interfaces
    "port": 80,  # HTTP port
}

# =============================================================================
# ENDPOINT CONFIGURATION
# =============================================================================

METRICS_ENDPOINT = "/metrics"  # Prometheus metrics endpoint path

# =============================================================================
# METRIC NAMES
# =============================================================================

METRIC_NAMES = {
    "temperature": "pico_temperature_celsius",
    "humidity": "pico_humidity_percent",
}

# Additional system metrics (automatically added to /metrics endpoint)
SYSTEM_METRIC_NAMES = {
    "sensor_status": "pico_sensor_status",
    "ota_status": "pico_ota_status",
    "version_info": "pico_version_info",
    "uptime": "pico_uptime_seconds",
}

# =============================================================================
# WIFI CONFIGURATION
# =============================================================================

WIFI_CONFIG = {
    "country_code": "GB",  # 2-letter country code
}
