import copy
import unittest
from datetime import datetime
from scripts.refresh_gate import already_refreshed, decide


class DailyRefreshTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-11-06T08:25:00+08:00")
        self.status = {name: {"ok": True, "checked": "2026-11-06T08:04:00+08:00"}
                       for name in ("clinical", "github")}

    def test_both_published_after_eight_skips(self):
        self.assertTrue(already_refreshed(self.status, self.now))
        self.assertFalse(decide(True, lambda: self.status, self.now)[0])

    def test_previous_day_does_not_suppress_today(self):
        self.status["clinical"]["checked"] = "2026-11-05T13:15:00+08:00"
        self.assertFalse(already_refreshed(self.status, self.now))

    def test_early_manual_refresh_does_not_replace_eight_am_refresh(self):
        self.status["github"]["checked"] = "2026-11-06T07:59:59+08:00"
        self.assertFalse(already_refreshed(self.status, self.now))

    def test_timezone_conversion_and_eight_boundary(self):
        for item in self.status.values():
            item["checked"] = "2026-11-06T00:00:00Z"
        self.assertTrue(already_refreshed(self.status, self.now))

    def test_failed_or_missing_module_retries(self):
        for name in self.status:
            state = copy.deepcopy(self.status)
            state[name]["ok"] = False
            self.assertFalse(already_refreshed(state, self.now))
            del state[name]
            self.assertFalse(already_refreshed(state, self.now))

    def test_invalid_future_and_naive_timestamps_cannot_skip(self):
        for bad in (None, 123, "bad", "2026-11-06T08:04:00", "2026-11-07T08:04:00+08:00"):
            self.status["github"]["checked"] = bad
            self.assertFalse(already_refreshed(self.status, self.now))
        self.assertFalse(already_refreshed([], self.now))

    def test_network_failure_runs_refresh(self):
        def unavailable():
            raise TimeoutError("unavailable")
        self.assertTrue(decide(True, unavailable, self.now)[0])

    def test_manual_refresh_bypasses_daily_gate(self):
        def should_not_fetch():
            self.fail("manual run must not read daily state")
        self.assertTrue(decide(False, should_not_fetch, self.now)[0])

    def test_partial_source_coverage_is_not_whole_pipeline_failure(self):
        self.status["clinical"]["degraded"] = True
        self.assertTrue(already_refreshed(self.status, self.now))
