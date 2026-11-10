import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from app.flows import runner as bot_runner
from app.utils import applied_log


class DailyLimitTests(unittest.TestCase):
    """The daily limit must survive restarts and hard kills."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.log_path = os.path.join(self.tmp.name, "applied_log.jsonl")
        patcher = patch.object(applied_log, "LOG_PATH", self.log_path)
        patcher.start()
        # Cleanups run LIFO: stop the patch, restore cwd, then remove the temp dir.
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, self.cwd)
        self.addCleanup(patcher.stop)

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _write_report(self, name, jobs, failed=None):
        os.makedirs(os.path.join("data", "reports"), exist_ok=True)
        with open(os.path.join("data", "reports", name), "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": self._today(),
                "jobs": jobs,
                "failed_jobs": failed or [],
            }, f)

    def test_counts_today_from_reports(self):
        self._write_report("r.json", [
            {"url": "u1", "applied_at": self._today()},
            {"url": "u2", "applied_at": self._today()},
        ])
        applied, count, failed = bot_runner._load_prior_applications()
        self.assertEqual(count, 2)
        self.assertEqual(applied, {"u1", "u2"})
        self.assertEqual(failed, set())

    def test_ignores_other_days(self):
        self._write_report("r.json", [{"url": "u1", "applied_at": "2020-01-01 10:00:00"}])
        applied, count, failed = bot_runner._load_prior_applications()
        self.assertEqual(count, 0)
        self.assertEqual(applied, {"u1"})

    def test_failed_today_not_counted_but_skipped(self):
        self._write_report("r.json", [], failed=[{"url": "f1", "attempted_at": self._today()}])
        applied, count, failed = bot_runner._load_prior_applications()
        self.assertEqual(count, 0)
        self.assertNotIn("f1", applied)
        self.assertIn("f1", failed)

    def test_durable_log_counts(self):
        applied_log.append_applied(
            [{"url": "u9", "title": "T", "company": "C"}], status="confirmed"
        )
        applied, count, failed = bot_runner._load_prior_applications()
        self.assertEqual(count, 1)
        self.assertIn("u9", applied)

    def test_durable_log_survives_report_loss(self):
        # Simulate a hard kill: the log has today's app, reports were never written.
        applied_log.append_applied(
            [{"url": "u7", "title": "T", "company": "C"},
             {"url": "u8", "title": "T2", "company": "C2"}],
            status="attempted",
        )
        applied, count, failed = bot_runner._load_prior_applications()
        self.assertEqual(count, 2)
        self.assertEqual(applied, {"u7", "u8"})

    def test_log_ignores_failed_records(self):
        applied_log.append_applied(
            [{"url": "u5", "title": "T", "company": "C"}], status="failed"
        )
        applied, count, failed = bot_runner._load_prior_applications()
        self.assertEqual(count, 0)
        self.assertNotIn("u5", applied)


if __name__ == "__main__":
    unittest.main()
