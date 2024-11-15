""" Python script to download images/vidoes from amcrest camera """

import os
import json
import re
import logging
import time
import uuid
import paho.mqtt.client as mqtt
import requests
from requests.auth import HTTPDigestAuth

# Logging setup
LOGFORMAT = "%(asctime)s  %(name)s  %(levelname)s: %(message)s"
loglevel = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(level=loglevel, format=LOGFORMAT)
logger = logging.getLogger("amarchiver")


class Config:
    """Configuration class for environment variables"""

    def __init__(self):
        self.mqtt_host = os.getenv("MQTT_HOST", "127.0.0.1")
        self.mqtt_port = os.getenv("MQTT_PORT", "1883")
        self.mqtt_user = os.getenv("MQTT_USER")
        self.mqtt_pass = os.getenv("MQTT_PASS")
        self.mqtt_src = os.getenv("MQTT_SRC", "test")
        self.cam_user = os.getenv("CAM_USER")
        self.cam_pass = os.getenv("CAM_PASS")
        self.cam_host = os.getenv("CAM_HOST")
        self.base_path = os.getenv("BASE_PATH", "/tmp")
        self.client_id = os.getenv("CLIENT_ID")


class CameraFileProcessor:
    """Handles the processing of camera files and MQTT interaction"""

    def __init__(self, config: Config):
        self.config = config

    def create_dir(self, path: str) -> None:
        """Create directory if it doesn't exist"""
        try:
            os.makedirs(path, exist_ok=True)  # 'exist_ok=True' avoids race conditions
        except OSError as e:
            logger.error("Failed to create path %s: %s", path, e)
            raise  # Rethrow exception to allow higher-level handling

    def get_file_name(self, file_path: str) -> str:
        """Extract filename from full file path"""
        return os.path.basename(file_path)

    def get_parts(self, file: str) -> dict:
        """Break down payload file into date, time, file type and name"""
        match = re.match(
            r"/mnt/sd/([0-9]+)-([0-9]+)-([0-9]+)/[0-9]+/(dav|jpg)/([0-9]+)/(.+)", file
        )
        if match:
            return {
                "year": match.group(1),
                "month": match.group(2),
                "day": match.group(3),
                "ext": match.group(4),
                "file_id": match.group(5),
                "filename": match.group(6),
            }
        return {}

    def get_path(self, parts: dict) -> str:
        """Create file destination path"""
        filename = parts["filename"].replace("/", "")  # sanitize filename
        path = os.path.join(
            parts["year"], parts["month"], parts["day"], parts["file_id"], parts["ext"]
        )
        return path, filename

    def get_file(self, file: str) -> bytes:
        """Download file from the camera"""
        url = f"http://{self.config.cam_host}/cgi-bin/RPC_Loadfile{file}"
        try:
            logger.info("Downloading file %s", url)
            req = requests.get(
                url,
                auth=HTTPDigestAuth(self.config.cam_user, self.config.cam_pass),
                timeout=10,
            )
            req.raise_for_status()  # Will raise an exception for HTTP errors
            return req.content
        except requests.exceptions.RequestException as e:
            logger.error("Failed to download file %s: %s", file, e)
            raise

    def save_file(self, file_bytes: bytes, path: str) -> None:
        """Save file content to the specified path"""
        try:
            with open(path, "wb") as localfile:
                localfile.write(file_bytes)
        except OSError as e:
            logger.error("Failed to save file %s: %s", path, e)
            raise

    def parse_msg(self, msg: str) -> dict:
        """Parse MQTT message payload, error on invalid json"""
        try:
            return json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            logger.error("Failed to parse message: %s", msg.payload)
            return {}

    def process_msg(self, payload: dict) -> None:
        """Process the message payload, download and save file"""
        file = payload["event_data"]["payload"]["data"]["File"]
        parts = self.get_parts(file)

        if not parts:
            logger.error("Invalid file path: %s", file)
            return

        os_path, file_name = self.get_path(parts)
        self.create_dir(os_path)

        try:
            file_bytes = self.get_file(file)
            file_path = os.path.join(os_path, file_name)
            self.save_file(file_bytes, file_path)
        except OSError as e:
            logger.error("Error processing file %s: %s", file, e)

    def on_connect(self, client, _userdata, _flags, rc, _properties):
        """Callback when the MQTT client connects, log status message"""
        if rc == 0:
            logger.info("Connected to MQTT Broker!")
            client.connected_flag = True
            client.subscribe(self.config.mqtt_src)
        else:
            logger.error("Failed to connect with code %s", rc)

    def on_disconnect(self, _client, _userdata, _flags, rc, _properties):
        """Callback when the MQTT client disconnects"""
        if rc == 0:
            logger.info("Closing connection to MQTT Broker!")
        else:
            logger.warning(
                "Disconnected error code %s, client should auto reconnect", rc
            )

    def on_message(self, _client, _userdata, msg: str) -> None:
        """Callback when an MQTT message is received, parse json message 
                and filter for correct event types"""
        payload = self.parse_msg(msg)

        if payload and payload.get("event_type") == "amcrest":
            event_data = payload.get("event_data", {})
            if event_data.get("event") == "NewFile" and "camera" in event_data:
                self.process_msg(payload)
            else:
                logger.info("Unhandled event: %s", payload)


def main():
    """Main function to start the MQTT client and process messages"""
    config = Config()
    camera_processor = CameraFileProcessor(config)

    if not config.client_id:
        config.client_id = str(uuid.uuid4())

    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=config.client_id,
    )
    if config.mqtt_user and config.mqtt_pass:
        mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_pass)

    mqtt_client.on_connect = camera_processor.on_connect
    mqtt_client.on_disconnect = camera_processor.on_disconnect
    mqtt_client.on_message = camera_processor.on_message
    mqtt_client.connect(config.mqtt_host, int(config.mqtt_port))
    mqtt_client.subscribe(config.mqtt_src)
    mqtt_client.loop_start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down due to keyboard interrupt")
        mqtt_client.disconnect()
        mqtt_client.loop_stop()


if __name__ == "__main__":
    main()
