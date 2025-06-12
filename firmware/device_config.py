"""
Device Configuration Management for Pico W Prometheus DHT22 Sensor

Handles persistent storage and management of device-specific configuration
such as location, device name, and description for dynamic Prometheus labels.
"""

import json
import time
import os

# Default configuration values
DEFAULT_CONFIG = {
    "device": {
        "location": "default-location",
        "name": "default-device",
        "description": ""
    },
    "ota": {
        "enabled": True,
        "auto_update": True,
        "update_interval": 1.0,
        "github_repo": {
            "owner": "TerrifiedBug",
            "name": "pico-w-prometheus-dht22",
            "branch": "main"
        }
    },
    "last_updated": ""
}

def load_device_config():
    """
    Load device configuration from JSON file.

    Returns:
        dict: Device configuration dictionary with location, device, description, and timestamp.
              Returns default configuration if file doesn't exist or is corrupted.
    """
    try:
        with open('device_config.json', 'r') as f:
            config = json.load(f)

        # Ensure all required keys exist and handle nested structure
        if "device" not in config:
            config["device"] = DEFAULT_CONFIG["device"].copy()
        if "ota" not in config:
            config["ota"] = DEFAULT_CONFIG["ota"].copy()
        if "last_updated" not in config:
            config["last_updated"] = DEFAULT_CONFIG["last_updated"]

        # Ensure nested device keys exist
        for key in DEFAULT_CONFIG["device"]:
            if key not in config["device"]:
                config["device"][key] = DEFAULT_CONFIG["device"][key]

        # Ensure nested OTA keys exist
        for key in DEFAULT_CONFIG["ota"]:
            if key not in config["ota"]:
                config["ota"][key] = DEFAULT_CONFIG["ota"][key]

        print(f"Device config loaded: {config['device']['location']}/{config['device']['name']}")
        return config

    except OSError:
        # File doesn't exist - first run
        print("Device config file not found, using defaults")
        return DEFAULT_CONFIG.copy()

    except ValueError:
        # JSON parsing error - corrupted file
        print("Device config file corrupted, using defaults")
        return DEFAULT_CONFIG.copy()

    except Exception as e:
        print(f"Error loading device config: {e}")
        return DEFAULT_CONFIG.copy()


def save_device_config(config):
    """
    Save device configuration to JSON file with atomic write operation.

    Args:
        config (dict): Configuration dictionary to save

    Returns:
        bool: True if save was successful, False otherwise
    """
    try:
        # Add timestamp
        config["last_updated"] = format_timestamp(time.time())

        # Atomic write with temporary file
        temp_file = 'device_config.json.tmp'

        with open(temp_file, 'w') as f:
            json.dump(config, f, indent=2)

        # Atomic rename operation
        try:
            os.rename(temp_file, 'device_config.json')
        except OSError:
            # On some systems, need to remove target first
            try:
                os.remove('device_config.json')
            except OSError:
                pass
            os.rename(temp_file, 'device_config.json')

        print(f"Device config saved: {config['device']['location']}/{config['device']['name']}")
        return True

    except Exception as e:
        print(f"Failed to save device config: {e}")

        # Clean up temporary file if it exists
        try:
            os.remove('device_config.json.tmp')
        except OSError:
            pass

        return False


def format_timestamp(timestamp):
    """
    Format timestamp for display in configuration.

    Args:
        timestamp (float): Unix timestamp

    Returns:
        str: Formatted timestamp string
    """
    try:
        # Simple timestamp formatting for MicroPython compatibility
        return str(int(timestamp))
    except:
        return ""


def validate_config_input(form_data):
    """
    Basic validation and sanitization of configuration input.

    Args:
        form_data (dict): Raw form data from HTTP request

    Returns:
        dict: Validated and sanitized configuration in new nested format
    """
    # Load current config to preserve existing values
    current_config = load_device_config()

    # Device configuration
    device_config = {}
    location = form_data.get("location", "").strip()
    device_config["location"] = location if location else "default-location"

    device_name = form_data.get("device", "").strip()
    device_config["name"] = device_name if device_name else "default-device"

    device_config["description"] = form_data.get("description", "").strip()

    # OTA configuration
    ota_config = current_config.get("ota", DEFAULT_CONFIG["ota"].copy())

    # Handle OTA form fields
    if "ota_enabled" in form_data:
        ota_config["enabled"] = form_data.get("ota_enabled") == "on"

    if "auto_update" in form_data:
        ota_config["auto_update"] = form_data.get("auto_update") == "on"

    if "update_interval" in form_data:
        try:
            interval = float(form_data.get("update_interval", 1.0))
            ota_config["update_interval"] = max(0.5, min(168.0, interval))  # 30 min to 1 week
        except (ValueError, TypeError):
            pass  # Keep existing value

    if "repo_owner" in form_data:
        owner = form_data.get("repo_owner", "").strip()
        if owner:
            ota_config["github_repo"]["owner"] = owner

    if "repo_name" in form_data:
        name = form_data.get("repo_name", "").strip()
        if name:
            ota_config["github_repo"]["name"] = name

    if "branch" in form_data:
        branch = form_data.get("branch", "").strip()
        if branch:
            ota_config["github_repo"]["branch"] = branch

    return {
        "device": device_config,
        "ota": ota_config,
        "last_updated": current_config.get("last_updated", "")
    }


def get_config_for_metrics():
    """
    Get configuration specifically formatted for Prometheus metrics labels.
    Ensures labels are safe for Prometheus format.

    Returns:
        dict: Configuration with Prometheus-safe label values
    """
    config = load_device_config()

    # Ensure we have valid values for metrics
    location = config.get("device", {}).get("location", "default-location")
    device = config.get("device", {}).get("name", "default-device")

    # Basic sanitization for Prometheus labels (remove quotes and backslashes)
    location = location.replace('"', '').replace('\\', '')
    device = device.replace('"', '').replace('\\', '')

    return {
        "location": location,
        "device": device,
        "description": config.get("device", {}).get("description", "")
    }


def get_ota_config():
    """
    Get OTA configuration for use by the OTA updater.

    Returns:
        dict: OTA configuration compatible with existing OTA updater
    """
    config = load_device_config()
    ota_config = config.get("ota", DEFAULT_CONFIG["ota"])

    # Convert to format expected by existing OTA updater
    return {
        "enabled": ota_config.get("enabled", True),
        "auto_check": ota_config.get("auto_update", True),
        "check_interval": int(ota_config.get("update_interval", 1.0) * 3600),  # Convert hours to seconds
        "github_repo": ota_config.get("github_repo", DEFAULT_CONFIG["ota"]["github_repo"]),
        "backup_enabled": True,
        "max_backup_versions": 3,
        "update_files": []  # Will be populated dynamically
    }


# Initialize configuration on module import
print("Initializing device configuration...")
_initial_config = load_device_config()
