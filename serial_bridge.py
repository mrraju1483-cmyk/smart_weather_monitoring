import json
import logging
import os
import time

import requests
import serial
from dotenv import load_dotenv

from backend.serial_service import validate_reading


load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("serial_bridge")


def read_settings():
    website_url = (os.getenv("RENDER_URL") or os.getenv("INGEST_URL") or "").strip().rstrip("/")
    ingest_token = (os.getenv("INGEST_TOKEN") or "").strip()
    serial_port = (os.getenv("SERIAL_PORT") or "COM3").strip()
    baud_rate = int(os.getenv("SERIAL_BAUD_RATE") or "9600")
    retry_seconds = float(os.getenv("SERIAL_RETRY_SECONDS") or "5")
    timeout_seconds = float(os.getenv("BRIDGE_HTTP_TIMEOUT_SECONDS") or "10")
    return website_url, ingest_token, serial_port, baud_rate, retry_seconds, timeout_seconds


def parse_reading(line):
    try:
        payload = json.loads(line)
        return validate_reading(payload)
    except (json.JSONDecodeError, ValueError):
        return None


def post_reading(session, ingest_url, ingest_token, reading, timeout_seconds):
    try:
        response = session.post(
            ingest_url,
            headers={
                "Authorization": f"Bearer {ingest_token}",
                "Content-Type": "application/json",
            },
            json=reading,
            timeout=timeout_seconds,
        )
        if response.status_code in (401, 403):
            logger.error("Render rejected the ingest token.")
            return False
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        logger.warning("Could not send sensor reading to Render: %s", error)
        return False


def main():
    website_url, ingest_token, serial_port, baud_rate, retry_seconds, timeout_seconds = read_settings()
    if not website_url:
        logger.error("Set RENDER_URL to your HTTPS Render website URL.")
        return 2
    if not website_url.lower().startswith("https://"):
        logger.error("RENDER_URL must use HTTPS.")
        return 2
    if not ingest_token:
        logger.error("Set INGEST_TOKEN to the same token configured on Render.")
        return 2

    ingest_url = f"{website_url}/api/ingest"
    session = requests.Session()

    while True:
        connection = None
        try:
            connection = serial.Serial(serial_port, baud_rate, timeout=1)
            time.sleep(2)
            logger.info("Opened %s at %d baud; forwarding JSON readings to %s", serial_port, baud_rate, ingest_url)
            while connection.is_open:
                raw = connection.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                reading = parse_reading(line)
                if reading is None:
                    continue
                if not post_reading(session, ingest_url, ingest_token, reading, timeout_seconds):
                    time.sleep(retry_seconds)
        except (serial.SerialException, OSError) as error:
            logger.warning("Arduino serial connection unavailable: %s", error)
        finally:
            if connection:
                if connection.is_open:
                    connection.close()
        time.sleep(retry_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
