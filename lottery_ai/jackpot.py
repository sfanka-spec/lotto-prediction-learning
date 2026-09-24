from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests

from .config import GAMES
from .providers import resilient_get, ProviderError, UA


@dataclass
class JackpotSnapshot:
    game: str
    observed_at: str
    source: str
    source_url: str
    jackpot_million: float | None = None
    classic_jackpot_million: float | None = None
    gold_ball_jackpot_million: float | None = None
    gold_balls_remaining: int | None = None
    maxplus_100k_count: int | None = None
    maxmillions_count: int | None = None
    jackpot_cap_million: float | None = None
    status: str = "CURRENT"
    raw_excerpt: str | None = None

    def to_dict(self):
        return asdict(self)


def _norm_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(html, "html.parser").get_text(" ")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _last_match(pattern: str, text: str, flags=re.I | re.S):
    ms = list(re.finditer(pattern, text, flags))
    return ms[-1] if ms else None


def parse_wclc_jackpot_widgets(text: str) -> dict:
    """Parse WCLC footer jackpot widgets from normalized page text.

    WCLC places both national jackpot widgets on many lottery pages. We keep the
    parser deliberately conservative: missing fields remain None instead of being
    inferred from unrelated historical prize text.
    """
    t = re.sub(r"\s+", " ", text or "").strip()
    out = {
        "649": {
            "gold_ball_jackpot_million": None,
            "gold_balls_remaining": None,
            "classic_jackpot_million": 5.0,
        },
        "max": {
            "jackpot_million": None,
            "maxplus_100k_count": None,
            "maxmillions_count": None,
        },
    }

    gb = _last_match(
        r"GOLD\s*BALL\s*JACKPOT\s*\$?\s*([0-9]+(?:\.[0-9]+)?)\s*MILLION"
        r".*?([0-9]+)\s*BALLS\s*REMAINING",
        t,
    )
    if gb:
        out["649"]["gold_ball_jackpot_million"] = float(gb.group(1))
        out["649"]["gold_balls_remaining"] = int(gb.group(2))

    # Current Lotto Max footer format, e.g. "$ 40 Million 40 x $100,000 Tuesday...".
    # Restrict the match to a draw-date trailer so historical MAXPLUS prize text is not
    # mistaken for the upcoming jackpot.
    mx = _last_match(
        r"\$?\s*([0-9]+(?:\.[0-9]+)?)\s*MILLION\s*([0-9]+)\s*[x×]\s*\$?\s*100\s*,?\s*000"
        r"\s*(?:PRIZES?\s*)?(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)",
        t,
    )
    if mx:
        out["max"]["jackpot_million"] = float(mx.group(1))
        out["max"]["maxplus_100k_count"] = int(mx.group(2))

    # Some regional pages expose "4 x MAXMILLIONS" near the current jackpot.
    mm = _last_match(r"([0-9]+)\s*[x×]\s*MAXMILLIONS", t)
    if mm:
        out["max"]["maxmillions_count"] = int(mm.group(1))
    return out


def crowd_pressure_proxy(game: str, snapshot: dict | None) -> dict:
    """A transparent *proxy*, never a claim about actual ticket sales.

    It intentionally uses only observed jackpot state. Actual sales volume can be
    added later when a trustworthy provider exposes it. This prevents the UI from
    labelling a guessed sales figure as factual.
    """
    s = snapshot or {}
    if game == "max":
        j = s.get("jackpot_million")
        cap = s.get("jackpot_cap_million") or 90.0
        if j is None:
            return {"level": "UNKNOWN", "score": None, "basis": "jackpot unavailable"}
        ratio = max(0.0, min(1.0, float(j) / float(cap)))
        # More secondary exact-match draws also increase attention/expected ticket value.
        mm = int(s.get("maxmillions_count") or 0)
        score = min(100.0, 80.0 * ratio + min(20.0, mm * 2.5))
    else:
        j = s.get("gold_ball_jackpot_million")
        cap = s.get("jackpot_cap_million") or 68.0
        if j is None:
            return {"level": "UNKNOWN", "score": None, "basis": "Gold Ball jackpot unavailable"}
        ratio = max(0.0, min(1.0, float(j) / float(cap)))
        # Crowd pressure must not mix in Gold-Ball ball count. Fewer balls improve the
        # conditional jackpot-vs-$1M outcome after a selection wins; that is prize
        # attractiveness, not evidence that more people bought tickets. Until verified
        # sales are available, jackpot level is the only crowd-attention proxy here.
        score = min(100.0, 100.0 * ratio)
    if score >= 85:
        level = "VERY HIGH"
    elif score >= 65:
        level = "HIGH"
    elif score >= 40:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {
        "level": level,
        "score": round(score, 2),
        "basis": "jackpot-state proxy; not measured sales volume",
    }


def jackpot_economics(game: str, snapshot: dict | None) -> dict:
    s = snapshot or {}
    pressure = crowd_pressure_proxy(game, s)
    if game == "max":
        jackpot = s.get("jackpot_million")
        cap = float(s.get("jackpot_cap_million") or 90.0)
        ratio = (float(jackpot) / cap) if jackpot is not None and cap else None
        return {
            "game": game,
            "jackpot_million": jackpot,
            "jackpot_cap_million": cap,
            "jackpot_cap_pct": None if ratio is None else round(100.0 * ratio, 2),
            "maxplus_100k_count": s.get("maxplus_100k_count"),
            "maxmillions_count": s.get("maxmillions_count"),
            "crowd_pressure_proxy": pressure,
            "play_cost": GAMES[game].play_cost,
            "note": "Crowd pressure is a jackpot-state proxy until actual sales data is available.",
        }

    jackpot = s.get("gold_ball_jackpot_million")
    balls = s.get("gold_balls_remaining")
    conditional_gold_prob = (1.0 / float(balls)) if balls else None
    conditional_prize_ev_million = None
    if jackpot is not None and balls:
        conditional_prize_ev_million = (
            conditional_gold_prob * float(jackpot)
            + (1.0 - conditional_gold_prob) * 1.0
        )
    conditional_value_score = None
    if balls:
        conditional_value_score = round(100.0 * max(0.0, min(1.0, (30.0 - float(balls)) / 29.0)), 2)
    return {
        "game": game,
        "classic_jackpot_million": float(s.get("classic_jackpot_million") or 5.0),
        "gold_ball_jackpot_million": jackpot,
        "jackpot_cap_million": float(s.get("jackpot_cap_million") or 68.0),
        "gold_balls_remaining": balls,
        "conditional_gold_ball_probability": conditional_gold_prob,
        "conditional_prize_ev_million_if_selection_wins": (
            None if conditional_prize_ev_million is None else round(conditional_prize_ev_million, 6)
        ),
        "gold_ball_conditional_value_score": conditional_value_score,
        "crowd_pressure_proxy": pressure,
        "play_cost": GAMES[game].play_cost,
        "note": (
            "Crowd pressure uses jackpot level only until verified sales are available. "
            "Gold-ball count is tracked separately as conditional prize attractiveness. "
            "Per-play Gold Ball odds still depend on the number of issued selections and are never invented."
        ),
    }


class WCLCJackpotProvider:
    """Latest official jackpot-state provider.

    This is intentionally separate from winning-number ingestion. Jackpot values are
    display/economics inputs and are never allowed to rewrite a frozen number prediction.
    """

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "en-CA,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })

    def fetch_widgets(self, source_url: str | None = None) -> tuple[dict, str, str]:
        url = source_url or GAMES["max"].official_url
        r = resilient_get(self.session, url, timeout=self.timeout)
        if r.status_code != 200:
            raise ProviderError(f"WCLC jackpot page returned HTTP {r.status_code}")
        text = _norm_html(r.text)
        parsed = parse_wclc_jackpot_widgets(text)
        return parsed, text, url

    def latest(self, game: str) -> dict:
        if game not in GAMES:
            raise KeyError(game)
        parsed, text, url = self.fetch_widgets(GAMES[game].official_url)
        observed = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        cfg = GAMES[game]
        if game == "max":
            p = parsed["max"]
            if p.get("jackpot_million") is None:
                raise ProviderError("Official page did not expose a parseable LOTTO MAX jackpot widget")
            snap = JackpotSnapshot(
                game=game,
                observed_at=observed,
                source="WCLC official jackpot widget",
                source_url=url,
                jackpot_million=p.get("jackpot_million"),
                maxplus_100k_count=p.get("maxplus_100k_count"),
                maxmillions_count=p.get("maxmillions_count"),
                jackpot_cap_million=cfg.jackpot_cap_million,
                raw_excerpt=text[-800:],
            )
        else:
            p = parsed["649"]
            if p.get("gold_ball_jackpot_million") is None:
                raise ProviderError("Official page did not expose a parseable Gold Ball jackpot widget")
            snap = JackpotSnapshot(
                game=game,
                observed_at=observed,
                source="WCLC official jackpot widget",
                source_url=url,
                classic_jackpot_million=5.0,
                gold_ball_jackpot_million=p.get("gold_ball_jackpot_million"),
                gold_balls_remaining=p.get("gold_balls_remaining"),
                jackpot_cap_million=cfg.jackpot_cap_million,
                raw_excerpt=text[-800:],
            )
        return snap.to_dict()
