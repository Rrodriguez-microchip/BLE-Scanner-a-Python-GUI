# BLE Scanner GUI

## Features

- **Device Discovery**: Scan and list nearby BLE devices with signal strength (RSSI)
- **Device Connection**: Connect to and manage BLE device connections with visual status indicators
- **Service Exploration**: Browse GATT services and characteristics with detailed property information
- **Data Communication**: Read/write data, subscribe to notifications with automatic polling fallback
- **Device Pairing**: Pair and unpair devices with session-based cleanup
- **Real-time Logging**: Timestamped activity log with comprehensive error handling
- **Cross-platform Support**: Works on Windows, macOS, and Linux

## Requirements

- Python 3.13 or higher
- `bleak` library for BLE operations
- `tkinter` (typically included with Python installations)

## Installation

1. Install the required dependency:
```bash
pip install bleak
```

2. Run the application:
```bash
python ble_scanner.py
```

## Usage

### Basic Workflow

1. **Scan for Devices**: Click "Start Scan" to discover nearby BLE devices
2. **Select Device**: Choose a device from the discovered list
3. **Connect**: Click "Connect" to establish a connection
4. **Explore Services**: View available services and characteristics in the "Services" tab
5. **Communicate**: Use the "Communication" tab to interact with device characteristics

### Communication Features

- **Reading Data**: Select a characteristic and click "Read" to retrieve current values
- **Writing Data**: Enter text in the input field and click "Send" to write data
- **Notifications**: Click "Subscribe" to receive automatic updates from the device
- **Pairing**: Use "Pair" button for devices requiring authentication

## Code Architecture

The application follows two main classes:

### BluetoothManager Class

Handles all BLE operations using the `bleak` library:

```python
class BluetoothManager:
    def __init__(self, callback_manager):
        self.callback_manager = callback_manager  # UI callback interface
        self.scanning = False                     # Scan state
        self.devices = {}                        # Discovered devices
        self.client = None                       # BLE client instance
        self.connected = False                   # Connection state
        self.notification_active = False         # Notification state
        self.paired_devices = set()              # Session paired devices
```

**Key Methods:**
- `start_scan()` / `stop_scan()`: Control device discovery
- `connect_to_device()` / `disconnect_from_device()`: Manage connections
- `send_data()` / `read_data()`: Handle data communication
- `start_notifications()` / `stop_notifications()`: Manage subscriptions
- `pair_device()` / `unpair_device()`: Handle device pairing

### BLEGUIApp Class

Manages the tkinter-based user interface:

```python
class BLEGUIApp:
    def __init__(self):
        self.root = tk.Tk()                      # Main window
        self.bluetooth = BluetoothManager(self)  # BLE manager instance
        self.selected_device_address = None      # Currently selected device
        self.selected_characteristic = None      # Currently selected characteristic
```

**UI Components:**
- Device discovery panel 
- Connection controls with status indicators
- Tabbed interface for services and communication
- Real-time data display with automatic scrolling

## Customization Guide

### Changing Scan Parameters

To modify scanning behavior, edit the `_scan_devices_simple()` method:

```python
# Change scan duration and interval
devices = await BleakScanner.discover(timeout=5.0)  # Increase scan time
await asyncio.sleep(1)  # Reduce scan interval
```

### Modifying Data Handling

To customize how data is processed, modify the notification handlers:

```python
def notification_handler(sender, data):
    # Custom data processing
    if len(data) > 0:
        # Example: Parse specific protocol
        if data[0] == 0x01:  # Custom header
            payload = data[1:]
            # Process payload...
```

### Adding Custom Device Filters

Filter devices during scanning by modifying the scan loop:

```python
for device in devices:
    # Filter by name pattern
    if device.name and "MyDevice" in device.name:
        # Only add devices matching criteria
        self.devices[device.address] = {...}
    
    # Filter by service UUIDs (requires advertisement data)
    # if "specific-service-uuid" in device.metadata.get("uuids", []):
```

### Customizing the UI Layout

#### Adding New Tabs

To add functionality tabs to the services notebook:

```python
def _setup_custom_tab(self):
    custom_tab = ttk.Frame(self.services_notebook)
    self.services_notebook.add(custom_tab, text="Custom")
    # Add custom widgets to custom_tab
```

#### Modifying Device Information Display

Extend device info by editing `_update_device_info()`:

```python
def _update_device_info(self, device_info):
    # Add additional fields
    self.manufacturer_label.config(text=device_info.get('manufacturer', 'Unknown'))
    self.tx_power_label.config(text=f"{device_info.get('tx_power', 'N/A')} dBm")
```

### Data Format Customization

#### Custom Data Encoding

Modify data encoding in `send_data()`:

```python
# Instead of UTF-8 encoding
data_bytes = data_str.encode('utf-8')

# Use custom encoding
data_bytes = bytes.fromhex(data_str)  # Hex string input
# or
data_bytes = struct.pack('<I', int(data_str))  # Integer as little-endian
```

#### Custom Data Parsing

Change how received data is displayed:

```python
def format_received_data(self, data):
    # Parse as JSON
    try:
        json_data = json.loads(data.decode('utf-8'))
        return f"JSON: {json.dumps(json_data, indent=2)}"
    except:
        # Fallback to hex
        return f"Raw: {' '.join(f'{b:02x}' for b in data)}"
```

### Threading and Async Customization

The application uses a hybrid threading approach. To modify async behavior:

```python
def _custom_async_operation(self, param):
    """Custom async operation with proper threading"""
    def async_thread():
        async def operation():
            # Your async code here
            result = await some_async_function(param)
            self.callback_manager.on_custom_result(result)
        
        # Standard async loop setup
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(operation())
        finally:
            try:
                loop.close()
            except:
                pass
    
    thread = threading.Thread(target=async_thread, daemon=True)
    thread.start()
```

### Error Handling Customization

Enhance error handling by modifying callback methods:

```python
def on_error(self, error_msg):
    # Log to file
    with open('ble_errors.log', 'a') as f:
        f.write(f"{datetime.now()}: {error_msg}\n")
    
    # Show different UI responses based on error type
    if "permission" in error_msg.lower():
        messagebox.showwarning("Permission Error", 
                              "Bluetooth permissions required")
    elif "timeout" in error_msg.lower():
        self.log("Connection timeout - device may be out of range")
```

### Adding Device-Specific Features

For specific device types, add custom handling:

```python
def handle_device_specific_features(self, device_info):
    # Detect device type
    if "Arduino" in device_info['name']:
        self.add_arduino_controls()
    elif "ESP32" in device_info['name']:
        self.add_esp32_controls()
    
def add_arduino_controls(self):
    # Add Arduino-specific UI elements
    arduino_frame = ttk.LabelFrame(self.right_frame, text="Arduino Controls")
    # Add custom buttons, sliders, etc.
```

## Common Use Cases

### IoT Device Development
- Monitor sensor data in real-time
- Send configuration commands
- Debug communication protocols

### BLE Learning and Education
- Explore BLE concepts hands-on
- Understand GATT services and characteristics
- Practice with different device types

### Device Testing
- Validate BLE implementation
- Test connection stability
- Verify data transmission

## Troubleshooting

### Connection Issues
- Ensure device is in pairing/advertising mode
- Check Bluetooth permissions on your system
- Try pairing after connecting for authentication-required devices

### Notification Problems
- The app automatically falls back to polling if notifications fail
- Some devices require pairing before notifications work
- Check that the characteristic supports notifications

## Dependencies

- **bleak**: Cross-platform BLE library
- **tkinter**: GUI framework (usually included with Python)
- **asyncio**: Asynchronous I/O (standard library)
- **threading**: Multi-threading support (standard library)

## License

This project is open source. Feel free to modify and distribute according to your needs.
