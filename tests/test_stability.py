from unittest.mock import patch

import pytest

from app import LotteryApp
from lottery_ai.analysis import paired_z_score
from lottery_ai.providers import ProviderError
from lottery_ai.updater import DataUpdater


class _AfterStub:
    def __init__(self):
        self.callback = None

    def after(self, delay, callback):
        assert delay == 0
        self.callback = callback


def test_safe_worker_preserves_exception_message_for_deferred_tk_callback():
    app = _AfterStub()

    def boom():
        raise RuntimeError("worker exploded")

    with patch("app.traceback.print_exc"), patch("app.logger.exception"), patch("app.messagebox.showerror") as show:
        LotteryApp._safe_worker(app, boom)
        assert app.callback is not None
        app.callback()
        show.assert_called_once_with("Lottery AI", "worker exploded")


def test_paired_z_score_zero_variance_is_conservative():
    assert paired_z_score([1.0, 1.0, 1.0, 1.0]) == 0.0
    assert paired_z_score([]) == 0.0
    assert paired_z_score([1.0]) == 0.0


def test_final_write_validation_rejects_bad_historical_record():
    class DBStub:
        def __init__(self):
            self.raw = []

        def save_raw(self, *args):
            self.raw.append(args)

    updater = object.__new__(DataUpdater)
    updater.db = DBStub()
    bad = {
        "date": "2020-01-01",
        "numbers": [1, 2, 3, 4, 5, 6, 52],
        "bonus": 7,
        "source": "test provider",
        "raw": {"fixture": True},
    }
    with pytest.raises(ProviderError):
        updater._require_valid_record("max", bad, "test write")
    assert updater.db.raw and updater.db.raw[-1][3] == "rejected"
