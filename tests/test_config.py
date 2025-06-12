"""
Test script for device configuration functionality
Run this to test the configuration system before deploying to the Pico W
"""

import json
import time
import os

# Import our device configuration module
from device_config import (
    load_device_config,
    save_device_config,
    validate_config_input,
    get_config_for_metrics,
    DEFAULT_CONFIG
)

def test_default_config():
    """Test loading default configuration"""
    print("=== Testing Default Configuration ===")

    # Remove config file if it exists
    try:
        os.remove('device_config.json')
    except:
        pass

    config = load_device_config()
    print(f"Default config: {config}")

    assert config["location"] == "default-location"
    assert config["device"] == "default-device"
    assert config["description"] == ""
    print("✓ Default configuration test passed")

def test_save_and_load():
    """Test saving and loading configuration"""
    print("\n=== Testing Save and Load ===")

    test_config = {
        "location": "kitchen",
        "device": "sensor-01",
        "description": "Kitchen temperature sensor"
    }

    # Save configuration
    success = save_device_config(test_config)
    assert success, "Failed to save configuration"
    print("✓ Configuration saved successfully")

    # Load configuration
    loaded_config = load_device_config()
    print(f"Loaded config: {loaded_config}")

    assert loaded_config["location"] == "kitchen"
    assert loaded_config["device"] == "sensor-01"
    assert loaded_config["description"] == "Kitchen temperature sensor"
    assert "last_updated" in loaded_config
    print("✓ Save and load test passed")

def test_validation():
    """Test input validation"""
    print("\n=== Testing Input Validation ===")

    # Test normal input
    form_data = {
        "location": "bedroom",
        "device": "temp-sensor",
        "description": "Main bedroom sensor"
    }

    validated = validate_config_input(form_data)
    print(f"Validated config: {validated}")

    assert validated["location"] == "bedroom"
    assert validated["device"] == "temp-sensor"
    assert validated["description"] == "Main bedroom sensor"
    print("✓ Normal validation test passed")

    # Test empty input (should use defaults)
    empty_data = {"location": "", "device": ""}
    validated_empty = validate_config_input(empty_data)
    print(f"Empty input validated: {validated_empty}")

    assert validated_empty["location"] == "default-location"
    assert validated_empty["device"] == "default-device"
    print("✓ Empty input validation test passed")

def test_metrics_format():
    """Test metrics formatting"""
    print("\n=== Testing Metrics Format ===")

    # Save a test configuration
    test_config = {
        "location": "living-room",
        "device": "sensor-02",
        "description": "Living room sensor"
    }
    save_device_config(test_config)

    # Get config for metrics
    metrics_config = get_config_for_metrics()
    print(f"Metrics config: {metrics_config}")

    assert metrics_config["location"] == "living-room"
    assert metrics_config["device"] == "sensor-02"

    # Test label formatting
    labels = f'{{location="{metrics_config["location"]}",device="{metrics_config["device"]}"}}'
    expected = '{location="living-room",device="sensor-02"}'
    assert labels == expected
    print(f"✓ Labels formatted correctly: {labels}")

def test_prometheus_labels():
    """Test Prometheus label sanitization"""
    print("\n=== Testing Prometheus Label Sanitization ===")

    # Test config with special characters
    test_config = {
        "location": 'kitchen"with"quotes',
        "device": 'sensor\\with\\backslashes',
        "description": "Test sensor"
    }
    save_device_config(test_config)

    metrics_config = get_config_for_metrics()
    print(f"Sanitized config: {metrics_config}")

    # Should have quotes and backslashes removed
    assert '"' not in metrics_config["location"]
    assert '\\' not in metrics_config["device"]
    print("✓ Prometheus label sanitization test passed")

def test_file_operations():
    """Test file operations and error handling"""
    print("\n=== Testing File Operations ===")

    # Test with valid JSON
    test_data = {
        "location": "garage",
        "device": "outdoor-sensor",
        "description": "Garage sensor",
        "last_updated": "1234567890"
    }

    with open('device_config.json', 'w') as f:
        json.dump(test_data, f)

    loaded = load_device_config()
    assert loaded["location"] == "garage"
    print("✓ Valid JSON file test passed")

    # Test with corrupted JSON
    with open('device_config.json', 'w') as f:
        f.write("invalid json content")

    loaded_corrupted = load_device_config()
    assert loaded_corrupted["location"] == "default-location"
    print("✓ Corrupted JSON handling test passed")

def run_all_tests():
    """Run all tests"""
    print("Starting Device Configuration Tests...")
    print("=" * 50)

    try:
        test_default_config()
        test_save_and_load()
        test_validation()
        test_metrics_format()
        test_prometheus_labels()
        test_file_operations()

        print("\n" + "=" * 50)
        print("🎉 ALL TESTS PASSED! 🎉")
        print("Device configuration system is working correctly.")

        # Show final configuration
        final_config = load_device_config()
        print(f"\nFinal configuration: {final_config}")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise

    finally:
        # Cleanup
        try:
            os.remove('device_config.json')
            os.remove('device_config.json.tmp')
        except:
            pass

if __name__ == "__main__":
    run_all_tests()
