"""BLE Scanner GUI Application

A comprehensive Bluetooth Low Energy (BLE) scanner application with GUI interface.

Features:
- Device scanning and discovery
- Connection management with pairing/unpairing
- Service and characteristic exploration
- Data read/write operations
- Real-time notifications with polling fallback
- Comprehensive logging and error handling
"""

import asyncio
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from bleak import BleakScanner, BleakClient
import threading
import time
from datetime import datetime
import sys
from typing import Dict, Any, Optional, List, Callable
from functools import wraps

# Configuration constants
SCAN_TIMEOUT = 2.0  # Seconds for each scan cycle
SCAN_INTERVAL = 2.0  # Seconds between scan cycles
POLLING_INTERVAL = 0.5  # Seconds between polling reads
NOTIFICATION_CHECK_INTERVAL = 0.1  # Seconds between notification queue checks
CLEANUP_TIMEOUT = 2.0  # Seconds to wait for cleanup completion
DEFAULT_RSSI = -50  # Default RSSI value when not available

# GUI configuration
WIDTH = 800
HEIGHT = 800
TREE_HEIGHT = 15
SERVICES_TEXT_HEIGHT = 10
RECEIVED_TEXT_HEIGHT = 8
LOG_TEXT_HEIGHT = 6


def run_async(func):
    """Decorator to run async functions in a dedicated event loop thread.
    
    Each decorated function will automatically run in its own event loop.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        def thread_target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(func(*args, **kwargs))
            finally:
                try:
                    loop.close()
                except:
                    pass
        
        thread = threading.Thread(target=thread_target, daemon=True)
        thread.start()
    
    return wrapper


def get_timestamp() -> str:
    """Get current timestamp in HH:MM:SS format."""
    return datetime.now().strftime("%H:%M:%S")


def format_data_message(data: bytes, message_type: str) -> str:
    """Format BLE data with timestamp and type.
    
    Args:
        data: Raw bytes received from BLE device
        message_type: Type of message (Read, Notification, Polled, etc.)
        
    Returns:
        Formatted message string with timestamp
    """
    timestamp = get_timestamp()
    
    try:
        # Try UTF-8 decoding first
        decoded_str = data.decode('utf-8')
        return f"[{timestamp}] {message_type}: '{decoded_str}'\n"
    except UnicodeDecodeError:
        # Fall back to hex representation for binary data
        hex_str = ' '.join([f'{b:02x}' for b in data])
        return f"[{timestamp}] {message_type} (hex): {hex_str}\n"


class BluetoothManager:
    """Handles all Bluetooth Low Energy operations.
    
    This class manages BLE device scanning, connection, pairing, and communication.
    It uses async operations run in background threads to prevent GUI blocking.
    All operations provide callbacks to the GUI for status updates.
    
    Attributes:
        callback_manager: GUI interface for status updates and user notifications
        scanning: Flag indicating if device scanning is active
        devices: Dictionary of discovered devices {address: device_info}
        client: Current BleakClient connection object
        connected: Flag indicating if a device is currently connected
        selected_characteristic: Currently selected BLE characteristic for operations
        notification_active: Flag indicating if notifications are active
        paired: Flag indicating if current device is paired
        paired_devices: Set of device addresses paired during this session
    """
    
    def __init__(self, callback_manager: 'BLEGUIApp') -> None:
        """Initialize the Bluetooth manager.        
        Args:
            callback_manager: GUI application instance that implements callback methods
        """
        self.callback_manager = callback_manager
        self.scanning = False
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.client: Optional[BleakClient] = None
        self.connected = False
        self.selected_characteristic = None
        self.notification_active = False
        self.paired = False
        self.paired_devices = set()  # Track devices paired during this session
        
    def start_scan(self) -> None:
        """Start BLE device scanning.
        
        Initiates continuous scanning for BLE devices. 
        Clears existing device list.
        Starts background scanning thread. 
        
        Updates GUI through callbacks.
        """
        self.scanning = True
        self.devices.clear()
        self.callback_manager.on_scan_started()
        
        # Run scan in background thread to avoid blocking GUI
        thread = threading.Thread(target=self._scan_devices_simple, daemon=True)
        thread.start()
    
    def stop_scan(self) -> None:
        """Stop BLE device scanning.
        
        Stops the continuous scanning process by setting the scanning flag to False.
        The background thread will terminate on its next iteration.
        """
        self.scanning = False
        self.callback_manager.on_scan_stopped()
    
    @run_async
    async def _scan_devices_simple(self) -> None:
        """Background async method for continuous BLE device scanning.
        
        Performs continuous scanning using BleakScanner.discover() without advertisement
        data to avoid compatibility issues. Updates device list and notifies GUI of changes.
        """
        while self.scanning:
            try:
                # Discover devices with timeout to prevent hanging
                devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT)
                
                # Process discovered devices
                for device in devices:
                    if device.address not in self.devices:
                        self.devices[device.address] = {
                            'name': device.name or "Unknown",
                            'address': device.address,
                            'rssi': DEFAULT_RSSI,  # Default value since we don't get RSSI in simple scan
                            'device': device
                        }
                        # Notify GUI of device list update
                        self.callback_manager.on_devices_updated(self.devices)
                
                # Wait between scans if still scanning
                if self.scanning:
                    await asyncio.sleep(SCAN_INTERVAL)
                    
            except Exception as e:
                error_msg = f"Scan error: {str(e)}"
                self.callback_manager.on_error(error_msg)
                break
    
    def connect_to_device(self, device_address: str) -> None:
        """        
        Args:
            device_address: MAC address of the device to connect to
            
        Note:
            Connection runs in background thread to prevent GUI blocking.
            GUI is updated through callbacks during the connection process.
        """
        if device_address not in self.devices:
            self.callback_manager.on_error(f"Device {device_address} not found in discovered devices")
            return
        
        device_info = self.devices[device_address]
        self.callback_manager.on_connection_started(device_info)
        
        # Run connection in background thread to avoid blocking GUI
        thread = threading.Thread(target=self._connect_simple, args=(device_address,), daemon=True)
        thread.start()
    
    @run_async
    async def _connect_simple(self, device_address: str) -> None:
        """Background async method for BLE device connection.
        Args:
            device_address: MAC address of the device to connect to
        """
        try:
            # Create and establish BLE client connection
            self.client = BleakClient(device_address)
            await self.client.connect()
            
            # Update connection status
            self.connected = True
            device_info = self.devices[device_address]
            self.callback_manager.on_connected(device_info)
            
            # Attempt to discover services and characteristics
            try:
                services = self.client.services
                self.callback_manager.on_services_discovered(services)
            except Exception as service_error:
                # Service discovery may fail on some devices, but connection is still valid
                self.callback_manager.on_message(
                    f"Connected - services discovery failed: {service_error}. "
                    "Services will be loaded when available."
                )
            
        except Exception as e:
            error_msg = f"Connection failed: {str(e)}"
            self.callback_manager.on_connection_failed(error_msg)
    
    def disconnect_from_device(self) -> None:
        """Disconnect from the currently connected BLE device.
        
        Stops any active notifications and initiates disconnection in background thread.
        Updates GUI state through callbacks upon completion.
        """
        if self.client:
            # Stop notifications before disconnecting
            self.notification_active = False
            thread = threading.Thread(target=self._disconnect_simple, daemon=True)
            thread.start()
        else:
            self.callback_manager.on_error("No device connected to disconnect from")
    
    @run_async
    async def _disconnect_simple(self) -> None:
        """Background async method for BLE device disconnection.
        
        Handles the disconnection process and updates connection state.
        Always calls the disconnected callback to ensure GUI state is updated.
        """
        try:
            if self.client:
                await self.client.disconnect()
                self.client = None
                self.connected = False
                self.paired = False
                self.selected_characteristic = None
                
        except Exception as e:
            error_msg = f"Disconnect error: {str(e)}"
            self.callback_manager.on_error(error_msg)
        finally:
            # Always update GUI state even if disconnect fails
            self.callback_manager.on_disconnected()
    
    def pair_device(self) -> None:
        """Initiate pairing with the currently connected BLE device.
        
        Pairing may be required for some BLE devices to access certain services
        or characteristics. This method tracks paired devices for cleanup on exit.
        
        Note:
            Requires an active connection. The device address is added to the
            paired_devices set for automatic cleanup when the application closes.
        """
        if not self.client:
            self.callback_manager.on_error("No device connected for pairing")
            return
        
        self.callback_manager.on_pairing_started()
        
        @run_async
        async def pair_async() -> None:
            """Async pairing operation."""
            try:
                await self.client.pair()
                self.paired = True
                
                # Track paired device for cleanup on application exit
                if self.client.address:
                    self.paired_devices.add(self.client.address)
                    
                self.callback_manager.on_paired_successfully()
                
            except Exception as e:
                error_msg = f"Pairing failed: {str(e)}"
                self.callback_manager.on_pairing_failed(error_msg)
        
        pair_async()
    
    def unpair_device(self) -> None:
        """Initiate unpairing from the currently connected BLE device.
        
        Removes the device from the system's paired device list and updates
        the internal tracking. The device can still be connected but may lose
        access to protected services.
        """
        if not self.client:
            self.callback_manager.on_error("No device connected for unpairing")
            return
        
        self.callback_manager.on_unpairing_started()
        
        def unpair_thread() -> None:
            """Background thread for unpairing operation."""
            async def unpair() -> None:
                """Async unpairing handler."""
                try:
                    await self.client.unpair()
                    self.paired = False
                    
                    # Remove from tracked paired devices
                    if self.client.address in self.paired_devices:
                        self.paired_devices.remove(self.client.address)
                        
                    self.callback_manager.on_unpaired_successfully()
                    
                except Exception as e:
                    error_msg = f"Unpairing failed: {str(e)}"
                    self.callback_manager.on_unpairing_failed(error_msg)
            
            # Run unpairing in dedicated event loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(unpair())
            except Exception as e:
                error_msg = f"Unpair thread error: {str(e)}"
                self.callback_manager.on_unpairing_failed(error_msg)
            finally:
                # Clean up event loop
                try:
                    loop.close()
                except:
                    pass  # Ignore cleanup errors
        
        thread = threading.Thread(target=unpair_thread, daemon=True)
        thread.start()
    
    def cleanup_all_paired_devices(self) -> None:
        """Clean up all devices paired during this application session.
        
        This method is called during application shutdown to ensure no devices
        remain paired after the application closes. It attempts to unpair each
        device that was paired during this session.
        
        Note:
            Each device requires a temporary connection to perform unpairing.
            Failures are logged but don't prevent cleanup of other devices.
        """
        if not self.paired_devices:
            self.callback_manager.on_message("No devices to unpair")
            return
        
        device_count = len(self.paired_devices)
        self.callback_manager.on_message(f"Unpairing {device_count} device(s)...")
        
        def cleanup_thread() -> None:
            """Background thread for cleanup operations."""
            async def cleanup_all() -> None:
                """Async cleanup handler that unpairs all tracked devices."""
                successful_unpairs = 0
                
                # Create a copy of the set to avoid modification during iteration
                devices_to_unpair = list(self.paired_devices)
                
                for device_address in devices_to_unpair:
                    try:
                        # Create temporary client for unpairing
                        temp_client = BleakClient(device_address)
                        await temp_client.connect()
                        await temp_client.unpair()
                        await temp_client.disconnect()
                        
                        # Remove from tracking set
                        self.paired_devices.discard(device_address)
                        successful_unpairs += 1
                        self.callback_manager.on_message(f"Unpaired device: {device_address}")
                        
                    except Exception as e:
                        self.callback_manager.on_message(
                            f"Failed to unpair {device_address}: {str(e)}"
                        )
                
                # Report final status
                if successful_unpairs == device_count:
                    self.callback_manager.on_message("All devices unpaired successfully")
                elif successful_unpairs > 0:
                    self.callback_manager.on_message(
                        f"Unpaired {successful_unpairs}/{device_count} devices"
                    )
                else:
                    self.callback_manager.on_message("No devices could be unpaired")
            
            # Run cleanup in dedicated event loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(cleanup_all())
            except Exception as e:
                error_msg = f"Cleanup thread error: {str(e)}"
                self.callback_manager.on_error(error_msg)
            finally:
                # Clean up event loop
                try:
                    loop.close()
                except:
                    pass  # Ignore cleanup errors
        
        thread = threading.Thread(target=cleanup_thread, daemon=True)
        thread.start()
    
    def send_data(self, characteristic, data_str: str) -> None:
        """Send string data to a BLE characteristic.
        
        Args:
            characteristic: BLE characteristic object with write capability
            data_str: String data to send (will be UTF-8 encoded)
            
        Note:
            Automatically selects write mode based on characteristic properties:
            - Uses write-without-response if supported for better performance
            - Falls back to write-with-response for reliable delivery
        """
        if not characteristic:
            self.callback_manager.on_error("No characteristic selected for sending data")
            return
            
        if not self.client or not self.connected:
            self.callback_manager.on_error("No device connected for sending data")
            return
        
        self.callback_manager.on_send_started(data_str)
        
        def write_thread() -> None:
            """Background thread for write operation."""
            async def write_data() -> None:
                """Async write handler that sends data to characteristic."""
                try:
                    # Encode string data to bytes
                    data_bytes = data_str.encode('utf-8')
                    
                    # Choose write mode based on characteristic capabilities
                    if "write-without-response" in characteristic.properties:
                        # Fast write without waiting for response
                        await self.client.write_gatt_char(
                            characteristic.uuid, data_bytes, response=False
                        )
                    else:
                        # Reliable write with response confirmation
                        await self.client.write_gatt_char(
                            characteristic.uuid, data_bytes, response=True
                        )
                    
                    self.callback_manager.on_send_success(data_str)
                    
                except Exception as e:
                    error_msg = f"Send failed: {str(e)}"
                    self.callback_manager.on_error(error_msg)
            
            # Run write operation in dedicated event loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(write_data())
            except Exception as e:
                error_msg = f"Write thread error: {str(e)}"
                self.callback_manager.on_error(error_msg)
            finally:
                # Clean up event loop
                try:
                    loop.close()
                except:
                    pass  # Ignore cleanup errors
        
        thread = threading.Thread(target=write_thread, daemon=True)
        thread.start()
    
    def read_data(self, characteristic) -> None:
        """Read data from a BLE characteristic.
        
        Args:
            characteristic: BLE characteristic object with read capability
            
        Note:
            Data is automatically decoded as UTF-8 text if possible, otherwise
            displayed as hexadecimal. Results are timestamped and sent to GUI.
        """
        if not characteristic:
            self.callback_manager.on_error("No characteristic selected for reading data")
            return
            
        if not self.client or not self.connected:
            self.callback_manager.on_error("No device connected for reading data")
            return
        
        self.callback_manager.on_read_started(characteristic.uuid)
        
        def read_thread() -> None:
            """Background thread for read operation."""
            async def read_data() -> None:
                """Async read handler that retrieves data from characteristic."""
                try:
                    # Read raw data from characteristic
                    data = await self.client.read_gatt_char(characteristic.uuid)
                    
                    # Format data for display with timestamp
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    
                    try:
                        # Try to decode as UTF-8 text
                        decoded_str = data.decode('utf-8')
                        message = f"[{timestamp}] Read: '{decoded_str}'\n"
                    except UnicodeDecodeError:
                        # Fall back to hex representation for binary data
                        hex_str = ' '.join([f'{b:02x}' for b in data])
                        message = f"[{timestamp}] Read (hex): {hex_str}\n"
                    
                    self.callback_manager.on_data_received(message)
                    
                except Exception as e:
                    error_msg = f"Read failed: {str(e)}"
                    self.callback_manager.on_error(error_msg)
            
            # Run read operation in dedicated event loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(read_data())
            except Exception as e:
                error_msg = f"Read thread error: {str(e)}"
                self.callback_manager.on_error(error_msg)
            finally:
                # Clean up event loop
                try:
                    loop.close()
                except:
                    pass  # Ignore cleanup errors
        
        thread = threading.Thread(target=read_thread, daemon=True)
        thread.start()
    
    def start_notifications(self, characteristic) -> None:
        """Start receiving notifications/indications from a BLE characteristic.
        
        Args:
            characteristic: BLE characteristic with notify or indicate capability
            
        This method attempts to use real BLE notifications first for optimal
        performance. If notifications fail, it automatically falls back to
        polling the characteristic at regular intervals.
        
        Note:
            Sets notification_active flag and stores the characteristic for
            potential polling fallback. Updates GUI through callbacks.
        """
        if not characteristic:
            self.callback_manager.on_error("No characteristic selected for notifications")
            return
            
        if not self.client or not self.connected:
            self.callback_manager.on_error("No device connected for notifications")
            return
        
        self.selected_characteristic = characteristic
        self.notification_active = True
        self.callback_manager.on_notifications_starting()
        
        def notification_thread() -> None:
            """Background thread for notification handling."""
            async def try_notifications() -> None:
                """Async handler that attempts real BLE notifications with polling fallback."""
                try:
                    def notification_handler(sender: int, data: bytearray) -> None:
                        """Callback for processing incoming BLE notifications.
                        
                        Args:
                            sender: Characteristic handle (unused)
                            data: Raw notification data
                        """
                        try:
                            # Format notification data with timestamp
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            
                            try:
                                # Try UTF-8 decoding first
                                decoded_str = data.decode('utf-8')
                                message = f"[{timestamp}] Notification: '{decoded_str}'\n"
                            except UnicodeDecodeError:
                                # Fall back to hex for binary data
                                hex_str = ' '.join([f'{b:02x}' for b in data])
                                message = f"[{timestamp}] Notification (hex): {hex_str}\n"
                                
                        except Exception as e:
                            # Handle any formatting errors
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            message = f"[{timestamp}] Notification (error): {str(e)}\n"
                        
                        # Add to notification queue for thread-safe GUI updates
                        if hasattr(self, '_notification_queue'):
                            self._notification_queue.append(message)
                    
                    # Initialize thread-safe notification queue
                    self._notification_queue = []
                    
                    # Attempt to start BLE notifications
                    await self.client.start_notify(characteristic.uuid, notification_handler)
                    self.callback_manager.on_notifications_started_real()
                    
                    # Process notification queue until stopped
                    while self.notification_active and self.connected:
                        # Process queued notifications
                        if hasattr(self, '_notification_queue') and self._notification_queue:
                            message = self._notification_queue.pop(0)
                            self.callback_manager.on_data_received(message)
                            
                        # Brief pause between queue checks
                        await asyncio.sleep(NOTIFICATION_CHECK_INTERVAL)
                    
                    # Clean up notifications when stopping
                    try:
                        await self.client.stop_notify(characteristic.uuid)
                    except:
                        pass  # Ignore stop notification errors
                    
                except Exception as e:
                    # Fall back to polling if real notifications fail
                    error_msg = f"Notifications failed, falling back to polling: {str(e)}"
                    self.callback_manager.on_message(error_msg)
                    self._start_polling_fallback(characteristic)
            
            # Run notification handling in dedicated event loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(try_notifications())
            except Exception as e:
                error_msg = f"Notification thread failed: {str(e)}"
                self.callback_manager.on_message(error_msg)
                self._start_polling_fallback(characteristic)
            finally:
                # Clean up event loop
                try:
                    loop.close()
                except:
                    pass  # Ignore cleanup errors
        
        thread = threading.Thread(target=notification_thread, daemon=True)
        thread.start()
    
    def _start_polling_fallback(self, characteristic) -> None:
        """Fallback notification method using periodic characteristic reads.
        
        Args:
            characteristic: BLE characteristic to poll for data changes
            
        This method is used when real BLE notifications are not supported or fail.
        It periodically reads the characteristic value and reports any data found.
        Less efficient than notifications but provides compatibility with more devices.
        """
        self.callback_manager.on_notifications_started_polling()
        
        # Send initial status message
        timestamp = datetime.now().strftime("%H:%M:%S")
        test_message = f"[{timestamp}] Polling started - checking for data every {POLLING_INTERVAL}s...\n"
        self.callback_manager.on_data_received(test_message)
        
        def poll_thread() -> None:
            """Background thread that performs periodic characteristic reads."""
            while self.notification_active and self.connected:
                try:
                    # Wait between polls
                    time.sleep(POLLING_INTERVAL)
                    
                    # Check if we should continue polling
                    if not self.notification_active or not self.connected:
                        break
                    
                    async def poll_read() -> None:
                        """Async read operation for polling."""
                        try:
                            # Verify connection is still valid before reading
                            if self.client and self.connected and self.notification_active:
                                # Read current characteristic value
                                data = await self.client.read_gatt_char(characteristic.uuid)
                                
                                # Format polled data with timestamp
                                timestamp = datetime.now().strftime("%H:%M:%S")
                                
                                try:
                                    # Try UTF-8 decoding
                                    decoded_str = data.decode('utf-8')
                                    message = f"[{timestamp}] Polled: '{decoded_str}'\n"
                                except UnicodeDecodeError:
                                    # Use hex representation for binary data
                                    hex_str = ' '.join([f'{b:02x}' for b in data])
                                    message = f"[{timestamp}] Polled (hex): {hex_str}\n"
                                
                                # Send to GUI if still active
                                if self.notification_active:
                                    self.callback_manager.on_data_received(message)
                                    
                        except Exception:
                            # Silently ignore read errors during polling
                            # This is normal if device disconnects or characteristic becomes unavailable
                            pass
                    
                    # Execute async read in temporary event loop
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(poll_read())
                    finally:
                        # Clean up temporary event loop
                        try:
                            loop.close()
                        except:
                            pass  # Ignore cleanup errors
                            
                except Exception:
                    # Exit polling thread on any major errors
                    break
        
        thread = threading.Thread(target=poll_thread, daemon=True)
        thread.start()
    
    def stop_notifications(self) -> None:
        """Stop active notifications or polling.
        
        Sets the notification_active flag to False, which signals background
        threads to stop processing notifications or polling operations.
        """
        self.notification_active = False
        self.callback_manager.on_notifications_stopped()
    
    def cleanup(self) -> None:
        """Clean up all BLE resources and unpair devices.
        
        This method is called during application shutdown to ensure proper
        cleanup of BLE connections and remove any paired devices from the system.
        
        Note:
            Stops all active operations and gives cleanup time to complete
            before the application fully exits.
        """
        # Stop all active BLE operations
        self.scanning = False
        self.notification_active = False
        
        # Clean up paired devices if any exist
        if self.paired_devices:
            self.cleanup_all_paired_devices()
            # Allow cleanup operations time to complete
            time.sleep(CLEANUP_TIMEOUT)


class BLEGUIApp:
    """Main GUI application class for BLE Scanner.
    
    This class creates and manages the complete graphical user interface for the
    BLE scanner application. It provides device discovery, connection management,
    service exploration, and data communication capabilities through a user-friendly
    tabbed interface.
    
    The class implements the callback interface required by BluetoothManager to
    receive status updates and data from BLE operations.
    
    Attributes:
        root: Main Tkinter window
        bluetooth: BluetoothManager instance for BLE operations
        selected_device_address: MAC address of currently selected device
        selected_characteristic: Currently selected BLE characteristic for operations
        
        GUI Components:
        - device_tree: TreeView showing discovered devices
        - services_text: Text widget displaying device services
        - char_combo: Combobox for characteristic selection
        - received_text: Text widget showing received data
        - log_text: Text widget for application logs
        - Various buttons for BLE operations
    """
    
    def __init__(self) -> None:
        """Initialize the BLE GUI application.
        
        Creates the main window, initializes the Bluetooth manager,
        and sets up the complete user interface.
        """
        # Create main application window
        self.root = tk.Tk()
        self.root.title("LightBlue-style BLE Scanner")
        self.root.geometry(f"{WIDTH}x{HEIGHT}")
        
        # Initialize Bluetooth manager with this app as callback handler
        self.bluetooth = BluetoothManager(self)
        
        # GUI state tracking variables
        self.selected_device_address: Optional[str] = None
        self.selected_characteristic = None
        
        # Build the complete user interface
        self.setup_ui()
        
    def setup_ui(self) -> None:
        """Build the complete user interface.
        
        Creates a responsive layout with:
        - Header with application title
        - Left panel for device discovery and selection
        - Right panel for device details and communication
        - Bottom log panel for status messages and errors
        """
        # Create main container frame with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure responsive grid layout
        self.root.columnconfigure(0, weight=1)  # Main frame expands
        self.root.rowconfigure(0, weight=1)     # Main frame expands
        main_frame.columnconfigure(1, weight=1)  # Right panel expands
        main_frame.rowconfigure(1, weight=1)     # Device panels expand
        
        # Build UI components in order
        self._setup_header(main_frame)
        self._setup_left_panel(main_frame)
        self._setup_right_panel(main_frame)
        self._setup_log_panel(main_frame)
        
    def _setup_header(self, parent: ttk.Frame) -> None:
        """Create the application header with title.
        
        Args:
            parent: Parent frame to contain the header
        """
        title_label = ttk.Label(
            parent, 
            text="BLE Device Scanner", 
            font=("Arial", 16, "bold")
        )
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 10))
    
    def _setup_left_panel(self, parent: ttk.Frame) -> None:
        """Create the left panel for device discovery and selection.
        
        Args:
            parent: Parent frame to contain the left panel
            
        Creates:
        - Scan control button
        - Device list with name, address, and RSSI columns
        - Scrollbar for device list navigation
        """
        # Create labeled frame for device discovery
        left_frame = ttk.LabelFrame(parent, text="Discovered Devices", padding="10")
        left_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        left_frame.columnconfigure(0, weight=1)  # Tree expands horizontally
        left_frame.rowconfigure(1, weight=1)     # Tree expands vertically
        
        # Scan control button
        self.scan_button = ttk.Button(
            left_frame, 
            text="Start Scan", 
            command=self._toggle_scan
        )
        self.scan_button.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Device discovery results tree view
        columns = ("name", "address", "rssi")
        self.device_tree = ttk.Treeview(
            left_frame, 
            columns=columns, 
            show="headings", 
            height=TREE_HEIGHT
        )
        
        # Configure column headers and widths
        self.device_tree.heading("name", text="Device Name")
        self.device_tree.heading("address", text="MAC Address")
        self.device_tree.heading("rssi", text="Signal")
        
        self.device_tree.column("name", width=150, minwidth=100)
        self.device_tree.column("address", width=120, minwidth=100)
        self.device_tree.column("rssi", width=60, minwidth=50)
        
        # Vertical scrollbar for device list
        tree_scroll = ttk.Scrollbar(
            left_frame, 
            orient="vertical", 
            command=self.device_tree.yview
        )
        self.device_tree.configure(yscrollcommand=tree_scroll.set)
        
        # Position tree and scrollbar
        self.device_tree.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scroll.grid(row=1, column=1, sticky=(tk.N, tk.S))
        
        # Bind device selection event
        self.device_tree.bind("<<TreeviewSelect>>", self._on_device_select)
    
    def _setup_right_panel(self, parent):
        """Set up the right panel with device details and communication"""
        right_frame = ttk.LabelFrame(parent, text="Device Details", padding="10")
        right_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5)
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(2, weight=1)
        
        self._setup_connection_controls(right_frame)
        self._setup_device_info(right_frame)
        self._setup_services_and_communication(right_frame)
    
    def _setup_connection_controls(self, parent):
        """Set up connection control buttons"""
        conn_frame = ttk.Frame(parent)
        conn_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        conn_frame.columnconfigure(0, weight=1)
        
        self.connect_button = ttk.Button(conn_frame, text="Connect", command=self._toggle_connection, state="disabled")
        self.connect_button.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        self.connection_status = ttk.Label(conn_frame, text="Status: Disconnected", foreground="red")
        self.connection_status.grid(row=1, column=0, pady=(5, 0))
    
    def _setup_device_info(self, parent):
        """Set up device information display"""
        info_frame = ttk.LabelFrame(parent, text="Device Information", padding="5")
        info_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        info_frame.columnconfigure(1, weight=1)
        
        ttk.Label(info_frame, text="Name:").grid(row=0, column=0, sticky=tk.W)
        self.name_label = ttk.Label(info_frame, text="-")
        self.name_label.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(10, 0))
        
        ttk.Label(info_frame, text="Address:").grid(row=1, column=0, sticky=tk.W)
        self.address_label = ttk.Label(info_frame, text="-")
        self.address_label.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(10, 0))
        
        ttk.Label(info_frame, text="RSSI:").grid(row=2, column=0, sticky=tk.W)
        self.rssi_label = ttk.Label(info_frame, text="-")
        self.rssi_label.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(10, 0))
    
    def _setup_services_and_communication(self, parent):
        """Set up services display and communication interface"""
        services_frame = ttk.LabelFrame(parent, text="Services & Characteristics", padding="5")
        services_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        services_frame.columnconfigure(0, weight=1)
        services_frame.rowconfigure(0, weight=1)
        
        # Create notebook for tabs
        self.services_notebook = ttk.Notebook(services_frame)
        self.services_notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self._setup_services_tab()
        self._setup_communication_tab()
    
    def _setup_services_tab(self):
        """Set up the services tab"""
        services_tab = ttk.Frame(self.services_notebook)
        self.services_notebook.add(services_tab, text="Services")
        services_tab.columnconfigure(0, weight=1)
        services_tab.rowconfigure(0, weight=1)
        
        self.services_text = scrolledtext.ScrolledText(services_tab, height=10, width=40)
        self.services_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    
    def _setup_communication_tab(self):
        """Set up the communication tab"""
        comm_tab = ttk.Frame(self.services_notebook)
        self.services_notebook.add(comm_tab, text="Communication")
        comm_tab.columnconfigure(0, weight=1)
        comm_tab.rowconfigure(3, weight=1)
        
        self._setup_characteristic_selection(comm_tab)
        self._setup_send_controls(comm_tab)
        self._setup_received_data_display(comm_tab)
    
    def _setup_characteristic_selection(self, parent):
        """Set up characteristic selection dropdown"""
        ttk.Label(parent, text="Select Characteristic:").grid(row=0, column=0, sticky=tk.W, pady=(0,5))
        self.char_var = tk.StringVar()
        self.char_combo = ttk.Combobox(parent, textvariable=self.char_var, state="readonly", width=35)
        self.char_combo.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0,10))
        self.char_combo.bind("<<ComboboxSelected>>", self._on_char_select)
    
    def _setup_send_controls(self, parent):
        """Set up send data controls"""
        send_frame = ttk.LabelFrame(parent, text="Send Data", padding="5")
        send_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0,10))
        send_frame.columnconfigure(0, weight=1)
        
        self.send_entry = ttk.Entry(send_frame, width=30)
        self.send_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0,5))
        self.send_entry.bind("<Return>", lambda e: self._send_data())
        
        send_buttons_frame = ttk.Frame(send_frame)
        send_buttons_frame.grid(row=0, column=1)
        
        self.send_button = ttk.Button(send_buttons_frame, text="Send", command=self._send_data, state="disabled")
        self.send_button.grid(row=0, column=0, padx=(0,5))
        
        self.notify_button = ttk.Button(send_buttons_frame, text="Subscribe", command=self._toggle_notifications, state="disabled")
        self.notify_button.grid(row=0, column=1, padx=(0,5))
        
        self.read_button = ttk.Button(send_buttons_frame, text="Read", command=self._read_data, state="disabled")
        self.read_button.grid(row=0, column=2, padx=(5,0))
        
        self.pair_button = ttk.Button(send_buttons_frame, text="Pair", command=self._pair_device, state="disabled")
        self.pair_button.grid(row=1, column=0, columnspan=2, pady=(5,0), sticky=(tk.W, tk.E))
        
        self.unpair_button = ttk.Button(send_buttons_frame, text="Unpair", command=self._unpair_device, state="disabled")
        self.unpair_button.grid(row=1, column=2, pady=(5,0), padx=(5,0), sticky=(tk.W, tk.E))
    
    def _setup_received_data_display(self, parent):
        """Set up received data display"""
        recv_frame = ttk.LabelFrame(parent, text="Received Data", padding="5")
        recv_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        recv_frame.columnconfigure(0, weight=1)
        recv_frame.rowconfigure(1, weight=1)
        
        # Status indicator
        status_frame = ttk.Frame(recv_frame)
        status_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0,5))
        status_frame.columnconfigure(1, weight=1)
        
        self.polling_status = ttk.Label(status_frame, text="● Idle", foreground="gray")
        self.polling_status.grid(row=0, column=0, sticky=tk.W)
        
        ttk.Label(status_frame, text="Messages will appear below:", font=("Arial", 8)).grid(row=0, column=1, sticky=tk.E)
        
        self.received_text = scrolledtext.ScrolledText(recv_frame, height=8, width=40)
        self.received_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Clear button
        clear_frame = ttk.Frame(recv_frame)
        clear_frame.grid(row=2, column=0, sticky=tk.E, pady=(5,0))
        
        ttk.Button(clear_frame, text="Clear", command=self._clear_received_data).grid(row=0, column=0)
    
    def _setup_log_panel(self, parent):
        """Set up the log panel"""
        log_frame = ttk.LabelFrame(parent, text="Log", padding="10")
        log_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=6)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure main grid weights
        parent.rowconfigure(2, weight=0)
    
    # Event handlers for GUI interactions
    def _toggle_scan(self):
        """Toggle BLE scanning"""
        if not self.bluetooth.scanning:
            self.bluetooth.start_scan()
        else:
            self.bluetooth.stop_scan()
    
    def _on_device_select(self, event):
        """Handle device selection"""
        selection = self.device_tree.selection()
        if selection:
            item = self.device_tree.item(selection[0])
            address = item['values'][1]
            
            if address in self.bluetooth.devices:
                self.selected_device_address = address
                device_info = self.bluetooth.devices[address]
                self._update_device_info(device_info)
                self.connect_button.config(state="normal")
    
    def _toggle_connection(self):
        """Toggle device connection"""
        if not self.bluetooth.connected:
            if self.selected_device_address:
                self.bluetooth.connect_to_device(self.selected_device_address)
        else:
            self.bluetooth.disconnect_from_device()
    
    def _pair_device(self):
        """Pair with device"""
        self.bluetooth.pair_device()
    
    def _unpair_device(self):
        """Unpair from device"""
        self.bluetooth.unpair_device()
    
    def _on_char_select(self, event):
        """Handle characteristic selection"""
        selection = self.char_combo.current()
        if selection >= 0 and hasattr(self.char_combo, 'char_uuids'):
            char_uuid = self.char_combo.char_uuids[selection]
            
            # Find the characteristic object
            for service in self.bluetooth.client.services:
                for char in service.characteristics:
                    if str(char.uuid) == char_uuid:
                        self.selected_characteristic = char
                        self._update_comm_buttons()
                        self.log(f"Selected characteristic: {char_uuid}")
                        return
    
    def _send_data(self):
        """Send data"""
        if self.selected_characteristic:
            data_str = self.send_entry.get().strip()
            if data_str:
                self.bluetooth.send_data(self.selected_characteristic, data_str)
    
    def _read_data(self):
        """Read data"""
        if self.selected_characteristic:
            self.bluetooth.read_data(self.selected_characteristic)
    
    def _toggle_notifications(self):
        """Toggle notifications"""
        if not self.bluetooth.notification_active:
            if self.selected_characteristic:
                self.bluetooth.start_notifications(self.selected_characteristic)
        else:
            self.bluetooth.stop_notifications()
    
    def _clear_received_data(self):
        """Clear received data display"""
        self.received_text.delete(1.0, tk.END)
    
    # UI update methods
    def _update_device_info(self, device_info):
        """Update device information display"""
        self.name_label.config(text=device_info['name'])
        self.address_label.config(text=device_info['address'])
        self.rssi_label.config(text=f"{device_info['rssi']} dBm")
    
    def _update_comm_buttons(self):
        """Update communication button states based on selected characteristic"""
        if not self.selected_characteristic:
            self.send_button.config(state="disabled")
            self.read_button.config(state="disabled")
            self.notify_button.config(state="disabled")
            return
        
        # Enable send button if characteristic supports write
        if any(prop in self.selected_characteristic.properties for prop in ["write", "write-without-response"]):
            self.send_button.config(state="normal")
        else:
            self.send_button.config(state="disabled")
        
        # Enable read button if characteristic supports read
        if "read" in self.selected_characteristic.properties:
            self.read_button.config(state="normal")
        else:
            self.read_button.config(state="disabled")
        
        # Enable notify button if characteristic supports notify/indicate
        if any(prop in self.selected_characteristic.properties for prop in ["notify", "indicate"]):
            if self.bluetooth.notification_active:
                self.notify_button.config(state="normal", text="Unsubscribe")
            else:
                self.notify_button.config(state="normal", text="Subscribe")
        else:
            self.notify_button.config(state="disabled")
    
    def log(self, message):
        """Add a timestamped message to the log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    # Callback methods - called by BluetoothManager
    def on_scan_started(self):
        """Called when scanning starts"""
        self.scan_button.config(text="Stop Scan")
        self._clear_device_tree()
        self.log("Starting BLE scan...")
    
    def on_scan_stopped(self):
        """Called when scanning stops"""
        self.scan_button.config(text="Start Scan")
        self.log("Stopped BLE scan")
    
    def on_devices_updated(self, devices):
        """Called when device list is updated"""
        self.root.after(0, self._update_device_tree, devices)
    
    def on_connection_started(self, device_info):
        """Called when connection attempt starts"""
        self.log(f"Connecting to {device_info['name']} ({device_info['address']})...")
        self.connect_button.config(text="Connecting...", state="disabled")
    
    def on_connected(self, device_info):
        """Called when device connection is successful"""
        self.connect_button.config(text="Disconnect", state="normal")
        self.connection_status.config(text="Status: Connected", foreground="green")
        self.pair_button.config(state="normal")
        self.log(f"Connected to {device_info['name']}")
    
    def on_connection_failed(self, error_msg):
        """Called when device connection fails"""
        self.connect_button.config(text="Connect", state="normal")
        self.connection_status.config(text="Status: Connection Failed", foreground="red")
        self.log(f"Connection failed: {error_msg}")
        messagebox.showerror("Connection Error", f"Failed to connect: {error_msg}")
    
    def on_disconnected(self):
        """Called when device is disconnected"""
        self.connect_button.config(text="Connect", state="normal")
        self.connection_status.config(text="Status: Disconnected", foreground="red")
        self.polling_status.config(text="● Idle", foreground="gray")
        self.services_text.delete(1.0, tk.END)
        self.received_text.delete(1.0, tk.END)
        self.char_combo['values'] = ()
        self.char_var.set("")
        self.selected_characteristic = None
        self.send_button.config(state="disabled")
        self.read_button.config(state="disabled")
        self.notify_button.config(state="disabled", text="Subscribe")
        self.pair_button.config(state="disabled")
        self.unpair_button.config(state="disabled")
        self.log("Disconnected from device")
    
    def on_services_discovered(self, services):
        """Called when services are discovered"""
        self.root.after(0, self._display_services, services)
    
    def on_pairing_started(self):
        """Called when pairing starts"""
        self.log("Attempting to pair with device...")
        self.pair_button.config(text="Pairing...", state="disabled")
    
    def on_paired_successfully(self):
        """Called when pairing succeeds"""
        self.log("Device paired successfully")
        self.pair_button.config(text="Paired", state="disabled")
        self.unpair_button.config(state="normal")
    
    def on_pairing_failed(self, error_msg):
        """Called when pairing fails"""
        self.log(f"Error: {error_msg}")
        self.pair_button.config(text="Pair", state="normal")
    
    def on_unpairing_started(self):
        """Called when unpairing starts"""
        self.log("Attempting to unpair from device...")
        self.unpair_button.config(text="Unpairing...", state="disabled")
    
    def on_unpaired_successfully(self):
        """Called when unpairing succeeds"""
        self.log("Device unpaired successfully")
        self.pair_button.config(text="Pair", state="normal")
        self.unpair_button.config(text="Unpair", state="disabled")
    
    def on_unpairing_failed(self, error_msg):
        """Called when unpairing fails"""
        self.log(f"Error: {error_msg}")
        self.unpair_button.config(text="Unpair", state="normal")
    
    def on_send_started(self, data_str):
        """Called when send operation starts"""
        self.log(f"Sending: '{data_str}'")
    
    def on_send_success(self, data_str):
        """Called when send operation succeeds"""
        self.log(f"Sent successfully: '{data_str}'")
        self.send_entry.delete(0, tk.END)
    
    def on_read_started(self, char_uuid):
        """Called when read operation starts"""
        self.log(f"Reading from: {char_uuid}")
    
    def on_data_received(self, message):
        """Called when data is received"""
        self.root.after(0, self._display_received_data, message)
    
    def on_notifications_starting(self):
        """Called when notifications are starting"""
        self.notify_button.config(text="Unsubscribe")
        self.polling_status.config(text="● Starting...", foreground="orange")
        self.log(f"Starting notifications for: {self.selected_characteristic.uuid}")
    
    def on_notifications_started_real(self):
        """Called when real BLE notifications start"""
        self.polling_status.config(text="● Notifications", foreground="blue")
        self.log("Real BLE notifications started")
    
    def on_notifications_started_polling(self):
        """Called when polling fallback starts"""
        self.polling_status.config(text="● Polling", foreground="green")
        self.log("Using polling fallback method")
    
    def on_notifications_stopped(self):
        """Called when notifications stop"""
        self.notify_button.config(text="Subscribe")
        self.polling_status.config(text="● Idle", foreground="gray")
        self.log("Stopped notifications")
    
    def on_message(self, message):
        """Called for general messages"""
        self.log(message)
    
    def on_error(self, error_msg):
        """Called for error messages"""
        self.log(f"Error: {error_msg}")
    
    # Helper methods for UI updates
    def _clear_device_tree(self):
        """Clear all items from device tree"""
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
    
    def _update_device_tree(self, devices):
        """Update the device tree with discovered devices"""
        self._clear_device_tree()
        
        # Add all devices
        for addr, device_info in devices.items():
            self.device_tree.insert("", "end", values=(
                device_info['name'],
                device_info['address'],
                f"{device_info['rssi']} dBm"
            ))
    
    def _display_services(self, services):
        """Display device services and characteristics"""
        self.services_text.delete(1.0, tk.END)
        char_list = []
        
        for service in services:
            self.services_text.insert(tk.END, f"Service: {service.uuid}\n")
            if service.description:
                self.services_text.insert(tk.END, f"  Description: {service.description}\n")
            
            for char in service.characteristics:
                self.services_text.insert(tk.END, f"  Characteristic: {char.uuid}\n")
                if char.description:
                    self.services_text.insert(tk.END, f"    Description: {char.description}\n")
                
                properties = []
                if "read" in char.properties:
                    properties.append("Read")
                if "write" in char.properties or "write-without-response" in char.properties:
                    properties.append("Write")
                if "notify" in char.properties:
                    properties.append("Notify")
                if "indicate" in char.properties:
                    properties.append("Indicate")
                
                if properties:
                    self.services_text.insert(tk.END, f"    Properties: {', '.join(properties)}\n")
                    
                    # Add writable/readable characteristics to dropdown
                    if any(prop in char.properties for prop in ["write", "write-without-response", "read", "notify", "indicate"]):
                        char_display = f"{char.uuid} ({', '.join(properties)})"
                        char_list.append((char_display, char.uuid))
                
                self.services_text.insert(tk.END, "\n")
            
            self.services_text.insert(tk.END, "\n")
        
        # Update characteristic dropdown
        if char_list:
            self.char_combo['values'] = [item[0] for item in char_list]
            self.char_combo.char_uuids = [item[1] for item in char_list]
    
    def _display_received_data(self, message):
        """Display received data in the text widget"""
        self.received_text.insert(tk.END, message)
        self.received_text.see(tk.END)
    
    def run(self):
        """Start the application"""
        self.log("BLE Scanner started. Click 'Start Scan' to discover devices.")
        self.log("Note: App will try real notifications first, then fall back to polling.")
        self.log("For some devices, you may need to click 'Pair' after connecting.")
        self.log("Paired devices will be automatically unpaired when you close the app.")
        
        # Handle window close event
        def on_closing():
            self.log("Closing application...")
            
            # Show a message if we're about to unpair devices
            if self.bluetooth.paired_devices:
                self.log(f"Unpairing {len(self.bluetooth.paired_devices)} paired device(s)...")
                # Start cleanup in background
                self.bluetooth.cleanup()
                # Give it a moment to start
                self.root.after(2000, self._force_close)  # Force close after 2 seconds
            else:
                self._force_close()
        
        def on_closing_immediate():
            """Immediate close without cleanup (in case cleanup hangs)"""
            self._force_close()
        
        # Bind both close events
        self.root.protocol("WM_DELETE_WINDOW", on_closing)
        
        # Add keyboard shortcut for immediate close (Ctrl+Q)
        self.root.bind("<Control-q>", lambda e: on_closing_immediate())
        
        self.root.mainloop()
    
    def _force_close(self):
        """Force close the application"""
        try:
            self.root.quit()
            self.root.destroy()
        except:
            pass  # Ignore any errors during close


if __name__ == "__main__":
    try:
        app = BLEGUIApp()
        app.run()
    except Exception as e:
        print(f"Error starting application: {e}")
        print("\nMake sure you have the required dependencies installed:")
        print("pip install bleak")
        print("\nNote: This application requires Bluetooth support on your system.")