from types import SimpleNamespace

from app import CollapsibleGameCard
from lottery_ai.config import APP_VERSION, GAMES


def _card(game_key: str, language_mode: str = "en"):
    card = object.__new__(CollapsibleGameCard)
    card.game_key = game_key
    card.cfg = GAMES[game_key]
    card.app = SimpleNamespace(language_mode=language_mode)
    return card


def test_v1551_version():
    assert APP_VERSION == "V1.6.6"


def test_lotto_max_next_draw_panel_includes_date_day_status_and_jackpot():
    card = _card("max", "en")
    text = card._current_draw_text(
        {
            "draw_date": "2026-09-18",
            "scheduled_today": False,
            "status": "NEXT_DRAW_WAITING",
            "result": None,
            "prediction_locked": False,
        },
        {"jackpot_million": 40.0, "status": "CURRENT"},
    )
    assert "Draw date: 2026-09-18 (Friday)" in text
    assert "NEXT DRAW" in text
    assert "Next jackpot: $40.0M" in text


def test_panel_is_never_blank_without_snapshot_or_jackpot():
    card = _card("max", "bilingual")
    text = card._current_draw_text(None, None)
    assert text.strip()
    assert "Next draw" in text
    assert "Next jackpot" in text


def test_lotto_649_keeps_equivalent_visible_prize_summary():
    card = _card("649", "en")
    text = card._current_draw_text(
        {"draw_date": "2026-09-19", "status": "NEXT_DRAW_WAITING"},
        {"classic_jackpot_million": 5.0, "gold_ball_jackpot_million": 30.0},
    )
    assert "Next prizes: Classic $5.0M | Gold Ball $30.0M" in text
