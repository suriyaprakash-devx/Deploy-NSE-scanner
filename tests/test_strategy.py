import asyncio
import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

# Importing the application also proves its routes and models load successfully.
import main

IST = ZoneInfo("Asia/Kolkata")

class StrategyTests(unittest.TestCase):
    def test_market_closed_on_weekend(self):
        old = main.now
        main.now = lambda: datetime(2026, 9, 19, 10, 0, tzinfo=IST)  # Saturday
        self.assertEqual(main.market(), "CLOSED")
        main.now = old

    def test_crossing_and_duplicate_prevention(self):
        # Isolate state in a disposable SQLite database; no external API is involved.
        previous = main.DB
        with tempfile.TemporaryDirectory() as directory:
            main.DB = os.path.join(directory, "test.db")
            main.init_db(); c = main.conn()
            c.execute("INSERT INTO levels VALUES ('NSE_EQ|TEST',100,90,'2026-09-18')")
            c.execute("INSERT INTO state VALUES ('NSE_EQ|TEST',99,1,1)"); c.commit(); c.close()
            asyncio.run(main.process("NSE_EQ|TEST", "TEST", 101))
            asyncio.run(main.process("NSE_EQ|TEST", "TEST", 102))
            self.assertEqual(len(main.rows("SELECT * FROM signals")), 1)
        main.DB = previous

    def test_invalid_price_is_ignored(self):
        # A missing/zero LTP cannot create a signal.
        asyncio.run(main.process("missing", "TEST", 0))

if __name__ == "__main__":
    unittest.main()
