from paho.mqtt import client as mqtt_client
import json
import logging
import time
import requests
import os
from requests.auth import HTTPDigestAuth
import re

# Logging
logformat = "%(asctime)s  %(name)s  %(levelname)s: %(message)s"
loglevel = os.getenv("LOG_LEVEL", default="INFO")
logging.basicConfig(level=loglevel, format=logformat)
logger = logging.getLogger(__name__)


# environment variables
mqtt_host = os.getenv("MQTT_HOST", "127.0.0.1")
mqtt_port = os.getenv("MQTT_PORT", "1883")
mqtt_user = os.getenv("MQTT_USER")
mqtt_pass = os.getenv("MQTT_PASS")
mqtt_src = os.getenv("MQTT_SRC", "test")
cam_user = os.getenv("CAM_USER")
cam_pass = os.getenv("CAM_PASS")
cam_host = os.getenv("CAM_HOST")
base_path = os.getenv("BASE_PATH", "/tmp")
logger.info(os.getenv("MQTT_SRC"))


def create_dir(path):
    if os.path.exists(path):
        return True
    else:
        try:
            os.makedirs(path)
            return True
        except:
            logger.warning(f'Failed to create path {path}')
            return False
        

def downloader(datafile, mediatype):
    
    parts = re.match("/mnt/sd/([0-9]*)-([0-9]*)-([0-9]*)/[0-9]*/(dav|jpg)/([0-9]*)/(.*)", datafile)

    if parts:
        year = parts[1]
        month = parts[2]
        day = parts[3]
        ftype = parts[4]
        hour = parts[5]
        filename = parts[6]


        path = os.path.join(base_path, f'{year}/{month}/{day}/{hour}/{ftype}')

        # remove slash from jpg image names
        filename = filename.replace('/','')

        logger.info(f"http://{cam_host}/cgi-bin/RPC_Loadfile{datafile}")

        if create_dir(path):
            try:
                req = requests.get(
                    f"http://{cam_host}/cgi-bin/RPC_Loadfile{datafile}",
                    auth=HTTPDigestAuth(cam_user, cam_pass),
                )

                with open(os.path.join(path,filename), "wb") as localfile:
                    localfile.write(req.content)
            except Exception as e:
                logger.warning(e)
                return

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        logger.info("Connected to MQTT Broker!")
        mqttclient.subscribe(mqtt_src)
    else:
        logger.error(f"Failed to connect, {rc}\n")


def on_disconnect(client, userdata, flags, rc, properties):
    logger.info("Disconnected to MQTT Broker!")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())

        if "event_type" in payload:

            if (
                payload["event_type"] == "amcrest"
                and "camera" in payload["event_data"]
                and payload["event_data"]["event"] == "NewFile"
            ):

                file = payload["event_data"]["payload"]["data"]["File"]

                if "mp4" in file:
                    mediatype = "video"
                else:
                    mediatype = "still"

                downloader(file, mediatype)
            else:
                logging.info(payload)
    except:
        logger.info(f"failed to parse message {msg.payload}")
        return


# Set Connecting Client ID
mqttclient = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)

# Set user/pass if set
if mqtt_user is not None and mqtt_pass is not None:
    mqttclient.username_pw_set(mqtt_user, mqtt_pass)

mqttclient.on_connect = on_connect
mqttclient.on_disconnect = on_disconnect
mqttclient.on_message = on_message
mqttclient._clean_session = True
mqttclient.connect(mqtt_host, int(mqtt_port))
mqttclient.loop_start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Received interrupt, shutting down")
    mqttclient.disconnect()
    mqttclient.loop_stop()
