"""
Configuration file for Pico W Prometheus DHT22 sensor project
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

# =============================================================================
# WIFI CONFIGURATION
# =============================================================================

WIFI_CONFIG = {
    "country_code": "GB",  # 2-letter country code
}
