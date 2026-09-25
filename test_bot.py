import tempfile
import threading
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import bot
import requests


CFG = {
    "api_key": "fake", "webhook": "https://discord.com/api/webhooks/123/fake",
    "service": "wx", "country": "62", "max_price": "1",
    "providers": "405", "threads": 20, "rate": 5,
    "timeout": 10, "status_every": 10, "max_purchases": 5, "sms_wait": 60,
}


class Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, results):
        self.results = iter(results)
        self.params = []

    def get(self, _url, params, timeout):
        self.params.append(params)
        return Response(next(self.results))


class BotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_state = bot.STATE
        bot.STATE = Path(self.directory.name) / "purchase.json"

    def tearDown(self):
        bot.STATE = self.original_state
        self.directory.cleanup()

    def test_default_settings_match_request_and_cap_price(self):
        with patch.dict(os.environ, {
            "GRIZZLY_API_KEY": "fake", "DISCORD_WEBHOOK_URL": CFG["webhook"],
        }, clear=True):
            self.assertEqual(bot.config(), CFG)
            os.environ["MAX_PRICE"] = "1.01"
            with self.assertRaises(ValueError):
                bot.config()

    def test_no_numbers_then_exactly_one_purchase(self):
        instance = bot.Bot(CFG)
        session = Session(["NO_NUMBERS", "ACCESS_NUMBER:123:905551234567"])
        with patch.object(bot, "send_discord") as send:
            instance.poll_once(session)
            self.assertEqual(bot.read_state()["status"], "idle")
            instance.poll_once(session)
        self.assertEqual(len(session.params), 2)
        self.assertEqual(session.params[1]["providerIds"], "405")
        self.assertEqual(session.params[1]["maxPrice"], "1")
        self.assertEqual(bot.read_state()["status"], "purchased")
        send.assert_called_once()

    def test_no_sms_cancels_then_buys_only_five_including_first(self):
        instance = bot.Bot(CFG)
        bot.save_state({"status": "purchased", "id": "1", "phone": "905551111111",
                        "acquired_at": 0, "notified": True,
                        "history": [{"id": "1", "phone": "905551111111", "result": "waiting"}]})
        responses = []
        for i in range(1, 5):
            responses += ["STATUS_WAIT_CODE", "ACCESS_CANCEL", f"ACCESS_NUMBER:{i+1}:90555111111{i+1}"]
        responses += ["STATUS_WAIT_CODE", "ACCESS_CANCEL"]
        session = Session(responses)
        with patch.object(bot, "send_discord"), patch.object(instance.stop, "wait", return_value=False), patch.object(bot.time, "time", return_value=120):
            for _ in range(4):
                instance.poll_once(session)
                instance.poll_once(session)
                state = bot.read_state()
                bot.save_state({**state, "acquired_at": 0})
            instance.poll_once(session)
        self.assertEqual([p["action"] for p in session.params].count("getNumber"), 4)
        self.assertEqual([p["action"] for p in session.params].count("setStatus"), 5)
        self.assertEqual(len(bot.read_state()["history"]), 5)
        self.assertEqual(bot.read_state()["status"], "exhausted")

    def test_sms_received_stops_before_next_purchase(self):
        instance = bot.Bot(CFG)
        bot.save_state({"status": "purchased", "id": "1", "phone": "905551111111",
                        "acquired_at": 0, "notified": True,
                        "history": [{"id": "1", "phone": "905551111111", "result": "waiting"}]})
        session = Session(["STATUS_OK:123456"])
        with patch.object(bot, "send_discord") as send, patch.object(instance.stop, "wait", return_value=False):
            instance.poll_once(session)
            instance.poll_once(session)
        self.assertEqual(len(session.params), 1)
        self.assertEqual(bot.read_state()["status"], "completed")
        self.assertEqual(bot.read_state()["code"], "123456")
        send.assert_called_once()

    def test_cancellation_failure_stops_without_another_charge(self):
        instance = bot.Bot(CFG)
        bot.save_state({"status": "purchased", "id": "1", "phone": "905551111111",
                        "acquired_at": 0, "notified": True,
                        "history": [{"id": "1", "phone": "905551111111", "result": "waiting"}]})
        session = Session(["STATUS_WAIT_CODE", "BAD_STATUS"])
        with patch.object(bot, "send_discord"), patch.object(instance.stop, "wait", return_value=False), patch.object(bot.time, "time", return_value=120):
            instance.poll_once(session)
            instance.poll_once(session)
        self.assertEqual([p["action"] for p in session.params], ["getStatus", "setStatus"])
        self.assertEqual(bot.read_state()["status"], "attempted")

    def test_previous_purchase_is_counted_on_startup(self):
        bot.save_state({"status": "purchased", "id": "1", "phone": "905551111111",
                        "notified": True})
        instance = bot.Bot(CFG)
        with patch.object(bot, "send_discord"), patch.object(instance, "worker"):
            instance.run()
        self.assertEqual(len(bot.read_state()["history"]), 1)
        self.assertIn("acquired_at", bot.read_state())

    def test_unclear_result_locks_all_threads(self):
        instance = bot.Bot(CFG)
        session = Session(["NO_BALANCE"])
        with patch.object(bot, "send_discord"):
            threads = [threading.Thread(target=instance.poll_once, args=(session,)) for _ in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(len(session.params), 1)
        self.assertEqual(bot.read_state()["status"], "attempted")

    def test_discord_failure_prevents_purchase(self):
        instance = bot.Bot(CFG)
        with patch.object(bot, "send_discord", side_effect=requests.ConnectionError):
            with patch.object(instance, "worker") as worker:
                with self.assertRaises(requests.ConnectionError):
                    instance.run()
                worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
