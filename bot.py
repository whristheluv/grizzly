"""Buy up to five Apple/Turkey numbers, checking each for SMS for one minute."""
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


LOG = logging.getLogger("grizzly")
API = "https://api.grizzlysms.com/stubs/handler_api.php"
load_dotenv(Path(__file__).with_name(".env"))
STATE = Path(os.getenv("STATE_FILE", str(Path(__file__).with_name("purchase.json"))))


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def setting(name, default):
    return os.getenv(name, default).strip()


def config():
    webhook = required("DISCORD_WEBHOOK_URL")
    parsed = urlparse(webhook)
    if parsed.scheme != "https" or parsed.hostname != "discord.com" or not parsed.path.startswith("/api/webhooks/"):
        raise ValueError("Invalid Discord webhook URL")
    price = setting("MAX_PRICE", "1")
    if not price.replace(".", "", 1).isdigit() or not 0 < float(price) <= 1:
        raise ValueError("MAX_PRICE must be between 0 and 1")
    ids = setting("PROVIDER_IDS", "405")
    if not all(part.isdigit() for part in ids.split(",")):
        raise ValueError("Invalid PROVIDER_IDS")
    cfg = {
        "api_key": required("GRIZZLY_API_KEY"), "webhook": webhook,
        "service": setting("SERVICE", "wx"), "country": setting("COUNTRY", "62"),
        "max_price": price, "providers": ids,
        "threads": int(setting("THREADS", "20")),
        "rate": float(setting("MAX_REQUESTS_PER_SECOND", "5")),
        "timeout": float(setting("REQUEST_TIMEOUT_SECONDS", "10")),
        "status_every": int(setting("STATUS_EVERY_REQUESTS", "10")),
        "max_purchases": 5,
        "sms_wait": 60,
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
        return {"status": "idle", "history": []}
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
            message = (f"✅ GrizzlySMS 번호 {len(state['history'])}/5 구매\n"
                       f"번호: {state['phone']}\n활성화 ID: {state['id']}\n"
                       "1분 동안 문자를 확인합니다.")
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

    def stop_for_review(self, state, reason):
        LOG.error("Stopped for manual review: %s", reason)
        save_state({**state, "status": "attempted", "reason": reason, "notified": False})
        self.stop.set()
        self.notify_pending(read_state())

    def expire_number(self, state, result):
        history = [*state["history"]]
        history[-1] = {**history[-1], "result": result}
        if len(history) >= self.cfg["max_purchases"]:
            save_state({"status": "exhausted", "history": history})
            self.stop.set()
            message = "⛔ 번호 총 5개까지 사용하여 검색을 종료했습니다."
        else:
            save_state({"status": "idle", "history": history})
            message = f"⏱️ 이전 번호에 문자가 없어 취소했습니다. 다음 번호를 검색합니다 ({len(history)}/5 사용)."
        try:
            send_discord(self.cfg, message)
        except requests.RequestException:
            self.stop_for_review(read_state(), "Discord notification failed before next purchase")

    def check_sms(self, session, state):
        if self.stop.wait(5):
            return
        try:
            response = session.get(API, params={
                "api_key": self.cfg["api_key"], "action": "getStatus", "id": state["id"],
            }, timeout=self.cfg["timeout"])
            response.raise_for_status()
        except requests.RequestException:
            self.stop_for_review(state, "SMS status request failed")
            return
        body = response.text.strip()
        if body.startswith("STATUS_OK:") and body.split(":", 1)[1]:
            code = body.split(":", 1)[1]
            save_state({**state, "status": "completed", "code": code})
            self.stop.set()
            send_discord(self.cfg, f"📩 SMS 수신! 번호: {state['phone']} / 인증번호: {code} (활성화 ID: {state['id']})")
            return
        if body == "STATUS_CANCEL":
            self.expire_number(state, "cancelled_by_provider")
            return
        if body not in ("STATUS_WAIT_CODE", "STATUS_WAIT_RESEND", "STATUS_WAIT_RETRY"):
            self.stop_for_review(state, "Unexpected SMS status")
            return
        if time.time() - state["acquired_at"] < self.cfg["sms_wait"]:
            return
        # Never buy again while the prior activation may still be active.
        try:
            cancelled = session.get(API, params={
                "api_key": self.cfg["api_key"], "action": "setStatus",
                "id": state["id"], "status": "8",
            }, timeout=self.cfg["timeout"])
            cancelled.raise_for_status()
        except requests.RequestException:
            self.stop_for_review(state, "Cancellation outcome unclear")
            return
        if cancelled.text.strip() != "ACCESS_CANCEL":
            self.stop_for_review(state, "Cancellation not confirmed")
            return
        self.expire_number(state, "cancelled_no_sms")

    def poll_once(self, session):
        # Only one charge-capable request may be in flight, including with 20 threads.
        with self.purchase_lock:
            if self.stop.is_set():
                return
            state = read_state()
            if state["status"] == "purchased":
                self.check_sms(session, state)
                return
            if state["status"] != "idle" or len(state["history"]) >= self.cfg["max_purchases"]:
                self.stop.set()
                return
            if not self.wait_for_slot():
                return
            save_state({"status": "attempted", "at": time.time(), "history": state["history"]})
            try:
                response = session.get(API, params={
                    "api_key": self.cfg["api_key"], "action": "getNumber",
                    "service": self.cfg["service"], "country": self.cfg["country"],
                    "maxPrice": self.cfg["max_price"], "providerIds": self.cfg["providers"],
                }, timeout=self.cfg["timeout"])
                response.raise_for_status()
            except requests.RequestException as error:
                LOG.error("Grizzly request outcome unclear: %s", type(error).__name__)
                self.stop_for_review(read_state(), "Purchase request outcome unclear")
                return

            self.requests += 1
            body = response.text.strip()
            if body == "NO_NUMBERS":
                save_state(state)
                self.no_numbers += 1
                if self.requests % self.cfg["status_every"] == 0:
                    LOG.info("still polling requests=%s no_numbers=%s", self.requests, self.no_numbers)
                return

            parts = body.split(":", 2)
            if len(parts) == 3 and parts[0] == "ACCESS_NUMBER" and all(part.isdigit() for part in parts[1:]):
                acquired_at = time.time()
                new_state = {"status": "purchased", "id": parts[1], "phone": parts[2],
                             "acquired_at": acquired_at, "notified": False,
                             "history": [*state["history"], {"id": parts[1], "phone": parts[2],
                                                             "result": "waiting"}]}
                save_state(new_state)
                LOG.info("Number acquired activation=%s", parts[1])
                self.notify_pending(new_state)
                return

            LOG.error("Grizzly response requires manual review")
            self.stop_for_review(read_state(), "Purchase response requires review")

    def worker(self):
        with requests.Session() as session:
            while not self.stop.is_set():
                self.poll_once(session)

    def run(self):
        state = read_state()
        if state["status"] == "purchased" and "history" not in state:
            # Existing DisHost purchase counts as the first of five; do not delete it.
            state = {**state, "acquired_at": time.time(),
                     "history": [{"id": state["id"], "phone": state["phone"], "result": "waiting"}]}
            save_state(state)
        if state["status"] == "idle" and "history" not in state:
            state = {"status": "idle", "history": []}
            save_state(state)
        if state["status"] not in ("idle", "purchased"):
            LOG.warning("Prior purchase state: %s; no further purchase attempts", state["status"])
            if state["status"] == "attempted":
                self.notify_pending(state)
            return
        if state["status"] == "purchased":
            self.notify_pending(state)
        LOG.info("startup service=%s country=%s maxPrice=%s providerIds=%s threads=%s rate=%s/s",
                 self.cfg["service"], self.cfg["country"], self.cfg["max_price"],
                 self.cfg["providers"], self.cfg["threads"], self.cfg["rate"])
        # Do not buy a number if its notification destination cannot be reached.
        send_discord(self.cfg, "🔎 GrizzlySMS Apple / Turkey 시작 (제공업체 405 / 번호당 최대 $1 / 총 5개)")
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
