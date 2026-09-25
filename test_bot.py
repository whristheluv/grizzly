import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import bot


CFG = {
    "api_key": "fake", "webhook": "https://discord.com/api/webhooks/123/fake",
    "service": "wx", "country": "62", "max_price": "1",
    "providers": "393,405,406,140", "threads": 20, "rate": 5,
    "timeout": 10, "status_every": 10,
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

    def test_no_numbers_then_exactly_one_purchase(self):
        instance = bot.Bot(CFG)
        session = Session(["NO_NUMBERS", "ACCESS_NUMBER:123:905551234567"])
        with patch.object(bot, "send_discord") as send:
            instance.poll_once(session)
            self.assertEqual(bot.read_state()["status"], "idle")
            instance.poll_once(session)
            instance.poll_once(session)
        self.assertEqual(len(session.params), 2)
        self.assertEqual(session.params[1]["providerIds"], "393,405,406,140")
        self.assertEqual(session.params[1]["maxPrice"], "1")
        self.assertEqual(bot.read_state()["status"], "purchased")
        send.assert_called_once()

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


if __name__ == "__main__":
    unittest.main()
