"""
Smart configuration loader for Pico W Prometheus DHT22 sensor project
Automatically detects environment and loads appropriate configuration
"""

import os

def detect_environment():
    """
    Detect the current environment based on version.txt format.

    Returns:
        str: Environment name ('development', 'production')
    """
    # Check version.txt format to determine environment
    try:
        with open('version.txt', 'r') as f:
            version = f.read().strip()
            if version.startswith('dev-'):
                return 'development'
            elif version.startswith('v'):
                return 'production'
    except:
        pass

    # Default to production for safety
    return 'production'

# =============================================================================
# BASE CONFIGURATION - SHARED ACROSS ALL ENVIRONMENTS
# =============================================================================

# SENSOR CONFIGURATION
SENSOR_CONFIG = {
    "pin": 2,  # GPIO pin for DHT22 sensor
    "read_interval": 30,  # Seconds between sensor readings
}

# SERVER CONFIGURATION
SERVER_CONFIG = {
    "host": "0.0.0.0",  # Listen on all interfaces
    "port": 80,  # HTTP port
}

# ENDPOINT CONFIGURATION
METRICS_ENDPOINT = "/metrics"  # Prometheus metrics endpoint path

# METRIC NAMES
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

# WIFI CONFIGURATION
WIFI_CONFIG = {
    "country_code": "GB",  # 2-letter country code
}

# BASE OTA UPDATE CONFIGURATION
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
        "ota_updater.py",
    ],
}

# =============================================================================
# ENVIRONMENT-SPECIFIC OVERRIDES
# =============================================================================

# Detect environment and apply overrides
environment = detect_environment()

try:
    # Apply environment-specific overrides
    if environment == 'development':
        print(f"Applying development overrides...")
        # Override for development environment
        OTA_CONFIG["github_repo"]["branch"] = "dev"
        OTA_CONFIG["check_interval"] = 1800  # 30 minutes
        SENSOR_CONFIG["read_interval"] = 10  # Faster for testing

        # Development environment variables
        ENVIRONMENT = "development"
        DEPLOYMENT_TYPE = "testing"

    elif environment == 'production':
        print(f"Applying production overrides...")
        # Override for production environment
        OTA_CONFIG["github_repo"]["branch"] = "main"
        OTA_CONFIG["check_interval"] = 3600  # 1 hour
        SENSOR_CONFIG["read_interval"] = 30  # Standard interval

        # Production environment variables
        ENVIRONMENT = "production"
        DEPLOYMENT_TYPE = "stable"

    LOADED_ENVIRONMENT = environment

except Exception as e:
    print(f"Failed to apply environment overrides: {e}")
    print("Using base configuration only...")
    LOADED_ENVIRONMENT = 'base'
    ENVIRONMENT = "unknown"
    DEPLOYMENT_TYPE = "unknown"

print(f"Configuration loaded: {LOADED_ENVIRONMENT} environment")
print(f"OTA branch: {OTA_CONFIG['github_repo']['branch']}")
