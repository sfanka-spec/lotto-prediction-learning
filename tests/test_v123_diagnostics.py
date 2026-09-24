from lottery_ai.config import GAMES
from lottery_ai.learning import LearningManager


class _PromotionDB:
    def __init__(self):
        self.saved = []
        self.logs = []

    def get_state(self, key, default=False):
        return True if key == "auto_promotion" else default

    def paired_model_performance(self, game_key, limit=200):
        # Positive, non-zero-variance paired edge; safely above the gate.
        rows = []
        for i in range(120):
            production = 0.90 + (i % 3) * 0.01
            challenger = production + (0.035 if i % 2 else 0.045)
            rows.append((f"2026-01-{(i % 28) + 1:02d}", production, challenger, 0.70))
        return rows

    def active_weights(self, game_key, role, defaults):
        if role == "challenger":
            w = dict(defaults)
            w["frequency"] += 0.01
            return w, "C1.9"
        return dict(defaults), "P1.4"

    def save_weights(self, *args, **kwargs):
        self.saved.append((args, kwargs))

    def add_learning_log(self, *args, **kwargs):
        self.logs.append((args, kwargs))


def test_auto_promotion_records_old_and_new_production_weights():
    db = _PromotionDB()
    lm = LearningManager(db)
    assert lm._maybe_promote("649") is True
    assert len(db.saved) == 1
    assert len(db.logs) == 1
    args, _ = db.logs[0]
    game, role, old_w, new_w, signal, reason = args
    assert game == "649"
    assert role == "production"
    assert old_w != {}
    assert new_w != {}
    assert old_w["monte_carlo"] == 0.0
    assert new_w["monte_carlo"] == 0.0
    assert signal["promoted_from"] == "C1.9"
    assert signal["previous_production"] == "P1.4"
    assert signal["new_production"] == "P1.5"
    assert "Auto-promoted C1.9" in reason
