# Dynamic Location Configuration Implementation

## Overview

This document describes the implementation of dynamic location configuration for the Pico W Prometheus DHT22 sensor project. This feature allows sensors to be moved around without requiring Prometheus configuration changes.

## Problem Solved

**Before**: Sensor locations were hardcoded in Prometheus configuration:

```yaml
- targets: ["192.168.1.100:80"]
  labels:
    location: bedroom # Fixed in prometheus.yml
```

**After**: Sensor locations are dynamically configured via web interface and included in metrics:

```prometheus
pico_temperature_celsius{location="bedroom",device="sensor-01"} 21.8
```

## Implementation Details

### 1. New Files Created

#### `device_config.py`

- **Purpose**: Manages persistent device configuration storage
- **Key Functions**:
  - `load_device_config()`: Load configuration from JSON file
  - `save_device_config()`: Atomic save with backup
  - `validate_config_input()`: Input validation and sanitization
  - `get_config_for_metrics()`: Prometheus-safe label formatting

#### `test_config.py`

- **Purpose**: Comprehensive test suite for configuration system
- **Tests**: Default config, save/load, validation, metrics formatting, error handling

### 2. Modified Files

#### `main.py`

- **Added**: Configuration management imports
- **Enhanced**: `format_metrics()` function with dynamic labels
- **New Endpoints**:
  - `GET /config`: HTML configuration form
  - `POST /config`: Configuration update handler
- **Added Functions**:
  - `handle_config_page()`: Serve configuration web interface
  - `handle_config_update()`: Process form submissions
  - `parse_form_data()`: HTTP form data parser

#### `config.py`

- **Added**: `device_config.py` to OTA update files list

### 3. Configuration Storage

#### File: `device_config.json`

```json
{
  "location": "bedroom",
  "device": "sensor-01",
  "description": "Main bedroom temperature sensor",
  "last_updated": "1749748554"
}
```

#### Default Values

- **Location**: `"default-location"`
- **Device**: `"default-device"`
- **Description**: `""` (empty)

### 4. Web Interface

#### Configuration Page (`/config`)

- Clean HTML form with current values pre-filled
- Real-time preview of current configuration
- Navigation links to other endpoints
- Responsive design with monospace font matching project style

#### Features

- **Form Fields**:
  - Location (text input)
  - Device Name (text input)
  - Description (textarea, optional)
- **Validation**: Client-side and server-side
- **Feedback**: Success/error messages
- **Navigation**: Links to main menu, health check, metrics

### 5. Prometheus Integration

#### Enhanced Metrics Format

```prometheus
# Before (static)
pico_temperature_celsius 21.8
pico_humidity_percent 55.4

# After (dynamic labels)
pico_temperature_celsius{location="bedroom",device="sensor-01"} 21.8
pico_humidity_percent{location="bedroom",device="sensor-01"} 55.4
pico_sensor_status{location="bedroom",device="sensor-01"} 1
pico_ota_status{location="bedroom",device="sensor-01"} 1
pico_uptime_seconds{location="bedroom",device="sensor-01"} 3600
pico_version_info{location="bedroom",device="sensor-01",version="v1.0.0"} 1
```

#### Label Sanitization

- Removes quotes (`"`) and backslashes (`\`) for Prometheus compatibility
- Handles empty values with defaults
- Ensures valid label format

### 6. Error Handling

#### File Operations

- **Atomic writes**: Uses temporary files with rename operation
- **Backup handling**: Automatic cleanup of temporary files
- **Corruption recovery**: Falls back to defaults if JSON is invalid
- **Missing file**: Creates default configuration automatically

#### Network Operations

- **Form parsing**: Handles malformed HTTP requests gracefully
- **URL decoding**: Basic URL decoding for form data
- **Validation**: Input sanitization and default value substitution

### 7. Integration Points

#### OTA Updates

- Configuration file included in update process
- Preserves settings across firmware updates
- Atomic operations prevent corruption during updates

#### Startup Process

- Configuration loaded at module import
- Default values used if file missing
- Logging of configuration status

## Usage Examples

### 1. Initial Setup

1. Deploy firmware to Pico W
2. Connect to device IP address
3. Visit `/config` endpoint
4. Set location and device name
5. Metrics immediately reflect new labels

### 2. Moving Sensors

1. Physically move sensor to new location
2. Visit `/config` on device
3. Update location field
4. Submit form
5. Prometheus automatically picks up new location

### 3. Prometheus Configuration

```yaml
# Simplified - no static labels needed
scrape_configs:
  - job_name: "pico_sensors"
    static_configs:
      - targets:
          - "192.168.1.100:80"
          - "192.168.1.101:80"
          - "192.168.1.102:80"
    # Labels now come from device metrics
```

### 4. Grafana Dashboards

```promql
# Query by location
pico_temperature_celsius{location="bedroom"}

# Query by device
pico_temperature_celsius{device="sensor-01"}

# Group by location
sum by (location) (pico_temperature_celsius)
```

## Benefits

### 1. Operational Flexibility

- **No Prometheus restarts**: Changes take effect immediately
- **Easy sensor relocation**: Update via web interface
- **Centralized management**: Each device manages its own identity

### 2. Scalability

- **Multiple sensors**: Each device has unique identity
- **Dynamic discovery**: Prometheus automatically sees new labels
- **Consistent labeling**: Standardized across all devices

### 3. Maintainability

- **Self-documenting**: Device description field
- **Audit trail**: Last updated timestamp
- **Error recovery**: Robust fallback mechanisms

### 4. User Experience

- **Web interface**: No command-line tools required
- **Immediate feedback**: Changes visible instantly
- **Intuitive design**: Simple form-based configuration

## Technical Specifications

### Memory Usage

- **Configuration file**: ~200 bytes typical
- **Runtime overhead**: Minimal (loaded once at startup)
- **Form processing**: Temporary allocation during updates

### Performance Impact

- **Metrics generation**: Negligible overhead for label formatting
- **Configuration loading**: One-time cost at startup
- **Web interface**: Standard HTTP request processing

### Compatibility

- **MicroPython**: Compatible with v1.20+
- **File system**: Uses standard JSON format
- **HTTP**: Standard form encoding
- **Prometheus**: Standard label format

### Security Considerations

- **Input validation**: Prevents injection attacks
- **File operations**: Atomic writes prevent corruption
- **Error handling**: No sensitive information in error messages
- **Access control**: Same as other device endpoints

## Future Enhancements

### Potential Additions

1. **API endpoint**: JSON-based configuration API
2. **Bulk configuration**: Configure multiple devices
3. **Configuration templates**: Predefined location/device combinations
4. **Validation rules**: Custom validation for location names
5. **Configuration history**: Track changes over time

### Integration Opportunities

1. **Home Assistant**: Auto-discovery integration
2. **MQTT**: Configuration via MQTT messages
3. **Network discovery**: Automatic device registration
4. **Configuration backup**: Cloud-based configuration storage

## Testing

### Test Coverage

- ✅ Default configuration loading
- ✅ Save and load operations
- ✅ Input validation and sanitization
- ✅ Metrics label formatting
- ✅ Prometheus label sanitization
- ✅ File operation error handling
- ✅ JSON corruption recovery

### Manual Testing

1. **Web interface**: Form submission and validation
2. **Metrics endpoint**: Label format verification
3. **Error scenarios**: File corruption, network errors
4. **Integration**: Prometheus scraping with new labels

## Conclusion

The dynamic location configuration feature successfully addresses the original requirement of eliminating the need to restart Prometheus when sensors are moved. The implementation follows the project's established patterns for reliability, error handling, and user experience while providing a flexible and scalable solution for sensor management.

The feature is production-ready and maintains backward compatibility while adding significant operational value to the sensor monitoring system.
