"""
Base configuration file for Pico W Prometheus DHT22 sensor project
This file contains shared settings across all environments
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

# =============================================================================
# BASE OTA UPDATE CONFIGURATION
# =============================================================================

# Over-The-Air Update Settings (base configuration)
OTA_CONFIG = {
    "enabled": True,
    "auto_check": True,  # Automatically check for updates
    "check_interval": 3600,  # Seconds between update checks (1 hour)
    "github_repo": {
        "owner": "TerrifiedBug",  # Replace with your GitHub username
        "name": "pico-w-prometheus-dht22",
        "branch": "main",  # Default to main branch (overridden by environment configs)
    },
    "backup_enabled": True,  # Backup files before update
    "max_backup_versions": 3,  # Keep N backup versions
    "update_files": [  # Files to update via OTA
        "main.py",
        "config.py",
        "config.base.py",
        "ota_updater.py",
    ],
}
