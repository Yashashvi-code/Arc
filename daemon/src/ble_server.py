import asyncio
import logging
import platform
import json
from db import ArcDatabase
from clipboard import ArcClipboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# UUIDs for Arc Service Profile
SERVICE_UUID = "4564ea7d-1c3c-44ef-a28a-7e61405e3201"
COORDINATES_CHAR_UUID = "4564ea7d-1c3c-44ef-a28a-7e61405e3202"
CLIPBOARD_CHAR_UUID = "4564ea7d-1c3c-44ef-a28a-7e61405e3203"

BLE_AVAILABLE = False
try:
    from bless import (
        BlessServer,
        BlessGATTCharacteristic,
        GATTCharacteristicProperties,
        GATTAttributePermissions,
    )
    BLE_AVAILABLE = True
except Exception as e:
    logging.warning(f"bless library failed to load ({e}). BLE server will run in MOCK mode.")

class ArcBleServer:
    def __init__(self, db=None, clipboard=None, on_coordinates_received=None):
        self.db = db or ArcDatabase()
        self.clipboard = clipboard or ArcClipboard(db=self.db)
        self.on_coordinates_received = on_coordinates_received
        self.server = None
        self.is_running = False

    def read_request(self, characteristic: 'BlessGATTCharacteristic', **kwargs) -> bytearray:
        logging.info(f"BLE read request for characteristic {characteristic.uuid}")
        return characteristic.value

    def write_request(self, characteristic: 'BlessGATTCharacteristic', value: bytearray, **kwargs):
        characteristic.value = value
        uuid_str = str(characteristic.uuid).lower()
        logging.info(f"BLE write request for characteristic {uuid_str}")

        try:
            decoded = value.decode('utf-8')
            if COORDINATES_CHAR_UUID in uuid_str:
                logging.info(f"Received coordinates from phone: {decoded}")
                if self.on_coordinates_received:
                    # Expecting host:port
                    parts = decoded.split(":")
                    if len(parts) == 2:
                        host, port_str = parts
                        port = int(port_str)
                        self.on_coordinates_received(host, port)
                        
            elif CLIPBOARD_CHAR_UUID in uuid_str:
                logging.info(f"Received clipboard text from phone: {decoded[:30]}...")
                # Write to system clipboard (will automatically update local system)
                self.clipboard.set_content(decoded)
                # Save to database
                self.db.insert_clipboard(decoded, is_file=False)
                
        except Exception as e:
            logging.error(f"Error handling write request: {e}")

    async def start(self):
        if not BLE_AVAILABLE:
            logging.info("BLE not available. Mock BLE server started successfully.")
            self.is_running = True
            return

        try:
            logging.info("Starting BLE GATT server...")
            self.server = BlessServer(name="arc-bridge-daemon")
            self.server.read_request_func = self.read_request
            self.server.write_request_func = self.write_request

            # 1. Add Service
            await self.server.add_new_service(SERVICE_UUID)

            # 2. Add Coordinates Characteristic (Write-only)
            coords_flags = GATTCharacteristicProperties.write
            coords_permissions = GATTAttributePermissions.writeable
            await self.server.add_new_characteristic(
                SERVICE_UUID,
                COORDINATES_CHAR_UUID,
                coords_flags,
                None,
                coords_permissions
            )

            # 3. Add Clipboard Characteristic (Read, Write, Notify)
            clip_flags = (
                GATTCharacteristicProperties.read |
                GATTCharacteristicProperties.write |
                GATTCharacteristicProperties.notify
            )
            clip_permissions = (
                GATTAttributePermissions.readable |
                GATTAttributePermissions.writeable
            )
            await self.server.add_new_characteristic(
                SERVICE_UUID,
                CLIPBOARD_CHAR_UUID,
                clip_flags,
                None,
                clip_permissions
            )

            # 4. Start advertising
            await self.server.start()
            self.is_running = True
            logging.info("BLE GATT server advertising as 'arc-bridge-daemon'.")
        except Exception as e:
            logging.error(f"Failed to start BLE GATT server: {e}")
            logging.info("Falling back to Mock BLE mode.")
            self.is_running = True

    async def notify_clipboard_change(self, text: str):
        if not self.is_running:
            return
            
        if not BLE_AVAILABLE or self.server is None:
            logging.info(f"[MOCK BLE] Simulating notify clipboard update: {text[:30]}...")
            return

        try:
            # Update value in GATT database
            char = self.server.get_characteristic(CLIPBOARD_CHAR_UUID)
            if char:
                char.value = text.encode('utf-8')
                # Trigger notification
                self.server.update_value(SERVICE_UUID, CLIPBOARD_CHAR_UUID)
                logging.info("BLE clipboard notification sent successfully.")
        except Exception as e:
            logging.error(f"Failed to send BLE notification: {e}")

    async def stop(self):
        if self.server and BLE_AVAILABLE:
            await self.server.stop()
            logging.info("BLE GATT server stopped.")
        self.is_running = False

if __name__ == "__main__":
    async def main():
        server = ArcBleServer()
        await server.start()
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await server.stop()
            
    asyncio.run(main())
