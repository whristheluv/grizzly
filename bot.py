"""Continuously buy one Apple/Turkey number from selected Grizzly providers."""
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


LOG = logging.getLogger("grizzly")
API = "https://api.grizzlysms.com/stubs/handler_api.php"
STATE = Path(os.getenv("STATE_FILE", "/data/purchase.json"))


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def config():
    webhook = required("DISCORD_WEBHOOK_URL")
    parsed = urlparse(webhook)
    if parsed.scheme != "https" or parsed.hostname != "discord.com" or not parsed.path.startswith("/api/webhooks/"):
        raise ValueError("Invalid Discord webhook URL")
    price = required("MAX_PRICE")
    if not price.replace(".", "", 1).isdigit() or not 0 < float(price) <= 1:
        raise ValueError("MAX_PRICE must be between 0 and 1")
    ids = required("PROVIDER_IDS")
    if not all(part.isdigit() for part in ids.split(",")):
        raise ValueError("Invalid PROVIDER_IDS")
    cfg = {
        "api_key": required("GRIZZLY_API_KEY"), "webhook": webhook,
        "service": required("SERVICE"), "country": required("COUNTRY"),
        "max_price": price, "providers": ids,
        "threads": int(required("THREADS")),
        "rate": float(required("MAX_REQUESTS_PER_SECOND")),
        "timeout": float(required("REQUEST_TIMEOUT_SECONDS")),
        "status_every": int(required("STATUS_EVERY_REQUESTS")),
    }
    if any(cfg[k] <= 0 for k in ("threads", "rate", "timeout", "status_every")):
        raise ValueError("Poll settings must be positive")
    return cfg


def save_state(value):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as file:
        json.dump(value, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, STATE)


def read_state():
    if not STATE.exists():
        return {"status": "idle"}
    return json.loads(STATE.read_text(encoding="utf-8"))


def send_discord(cfg, message):
    response = requests.post(cfg["webhook"], json={
        "content": message, "allowed_mentions": {"parse": []},
    }, timeout=cfg["timeout"])
    response.raise_for_status()


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.stop = threading.Event()
        self.purchase_lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.next_request = 0.0
        self.requests = 0
        self.no_numbers = 0

    def wait_for_slot(self):
        with self.rate_lock:
            delay = max(0, self.next_request - time.monotonic())
            self.next_request = time.monotonic() + delay + 1 / self.cfg["rate"]
        return not self.stop.wait(delay)

    def notify_pending(self, state):
        if state["status"] == "purchased":
            message = ("✅ GrizzlySMS Apple / Turkey 번호 구매 완료\n"
                       f"번호: {state['phone']}\n활성화 ID: {state['id']}")
        else:
            message = ("⚠️ GrizzlySMS 번호 구매 결과를 확인할 수 없어 중지했습니다. "
                       "GrizzlySMS 활성화 목록을 확인해 주세요.")
        if state.get("notified"):
            return
        try:
            send_discord(self.cfg, message)
            save_state({**state, "notified": True})
        except requests.RequestException as error:
            LOG.warning("Discord notification failed: %s", type(error).__name__)

    def poll_once(self, session):
        # Only one charge-capable request may be in flight, including with 20 threads.
        with self.purchase_lock:
            if self.stop.is_set() or not self.wait_for_slot():
                return
            save_state({"status": "attempted", "at": time.time()})
            try:
                response = session.get(API, params={
                    "api_key": self.cfg["api_key"], "action": "getNumber",
                    "service": self.cfg["service"], "country": self.cfg["country"],
                    "maxPrice": self.cfg["max_price"], "providerIds": self.cfg["providers"],
                }, timeout=self.cfg["timeout"])
                response.raise_for_status()
            except requests.RequestException as error:
                LOG.error("Grizzly request outcome unclear: %s", type(error).__name__)
                self.stop.set()
                self.notify_pending(read_state())
                return

            self.requests += 1
            body = response.text.strip()
            if body == "NO_NUMBERS":
                save_state({"status": "idle"})
                self.no_numbers += 1
                if self.requests % self.cfg["status_every"] == 0:
                    LOG.info("still polling requests=%s no_numbers=%s", self.requests, self.no_numbers)
                return

            parts = body.split(":", 2)
            if len(parts) == 3 and parts[0] == "ACCESS_NUMBER" and all(part.isdigit() for part in parts[1:]):
                state = {"status": "purchased", "id": parts[1], "phone": parts[2], "notified": False}
                save_state(state)
                self.stop.set()
                LOG.info("Number acquired activation=%s", parts[1])
                self.notify_pending(state)
                return

            LOG.error("Grizzly response requires manual review")
            self.stop.set()
            self.notify_pending(read_state())

    def worker(self):
        with requests.Session() as session:
            while not self.stop.is_set():
                self.poll_once(session)

    def run(self):
        state = read_state()
        if state["status"] != "idle":
            LOG.warning("Prior purchase state: %s; no further purchase attempts", state["status"])
            self.notify_pending(state)
            return
        LOG.info("startup service=%s country=%s maxPrice=%s providerIds=%s threads=%s rate=%s/s",
                 self.cfg["service"], self.cfg["country"], self.cfg["max_price"],
                 self.cfg["providers"], self.cfg["threads"], self.cfg["rate"])
        try:
            send_discord(self.cfg, "🔎 GrizzlySMS Apple / Turkey 번호 검색 시작 (제공업체 393,405,406,140 / 최대 $1)")
        except requests.RequestException as error:
            LOG.warning("Discord startup test failed: %s", type(error).__name__)
        workers = [threading.Thread(target=self.worker, name=f"poll-{i}")
                   for i in range(self.cfg["threads"])]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s")
    bot = Bot(config())
    signal.signal(signal.SIGTERM, lambda *_: bot.stop.set())
    signal.signal(signal.SIGINT, lambda *_: bot.stop.set())
    bot.run()


if __name__ == "__main__":
    main()
