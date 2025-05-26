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

def load_config():
    """
    Load base configuration and apply environment-specific overrides.

    Returns:
        str: The loaded environment name
    """
    environment = detect_environment()

    try:
        # Always start with base configuration
        print(f"Loading base configuration...")
        from config.base import *

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

        # Update globals with all variables
        globals().update({k: v for k, v in locals().items() if not k.startswith('_')})
        return environment

    except Exception as e:
        print(f"Failed to load configuration: {e}")
        print("Using base configuration only...")
        from config.base import *
        globals().update({k: v for k, v in locals().items() if not k.startswith('_')})
        return 'base'

# Auto-load configuration on import
LOADED_ENVIRONMENT = load_config()

# Re-export all configuration variables for backward compatibility
try:
    # These will be available after load_config() runs
    __all__ = [
        'SENSOR_CONFIG',
        'SERVER_CONFIG',
        'METRICS_ENDPOINT',
        'METRIC_NAMES',
        'SYSTEM_METRIC_NAMES',
        'WIFI_CONFIG',
        'OTA_CONFIG',
        'ENVIRONMENT',
        'DEPLOYMENT_TYPE',
        'MONITORING_CONFIG',
        'LOADED_ENVIRONMENT'
    ]
except:
    pass

print(f"Configuration loaded: {LOADED_ENVIRONMENT} environment")
if 'OTA_CONFIG' in globals():
    print(f"OTA branch: {OTA_CONFIG['github_repo']['branch']}")
