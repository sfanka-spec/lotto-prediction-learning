from __future__ import annotations

import logging
import re
import time
from email.utils import parsedate_to_datetime
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import requests

from .config import GAMES
from .regime import regime_for

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0 Safari/537.36 LotteryAI/1.6.5"

class ProviderError(RuntimeError):
    pass


def _retry_after_seconds(response, fallback: float) -> float:
    raw = str((getattr(response, "headers", {}) or {}).get("Retry-After", "")).strip()
    if raw:
        try:
            return max(0.0, min(30.0, float(raw)))
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                seconds = (dt - datetime.now(timezone.utc)).total_seconds()
                return max(0.0, min(30.0, seconds))
            except Exception:
                pass
    return max(0.0, min(30.0, float(fallback)))


def resilient_get(session, url, *, timeout=20, params=None, retries=3):
    """HTTP GET with bounded retry/backoff for transient resets/timeouts.

    HTTP 408 and 429 are retryable. 429 honors ``Retry-After`` when supplied, capped
    at 30 seconds. Other 4xx responses return immediately; 5xx and connection/read
    failures use bounded 2s/5s/12s backoff.
    """
    delays = (2, 5, 12)
    last = None
    total_attempts = max(1, int(retries))
    for attempt in range(total_attempts):
        retry_delay = delays[min(attempt, len(delays)-1)]
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code not in (408, 429) and r.status_code < 500:
                return r
            last = ProviderError(f"HTTP {r.status_code}")
            if r.status_code in (408, 429):
                retry_delay = _retry_after_seconds(r, retry_delay)
        except (requests.RequestException, ConnectionResetError, OSError) as e:
            last = e
            logger.warning("Provider request failed attempt %s/%s url=%s: %s", attempt + 1, total_attempts, url, e)
        if attempt < total_attempts - 1:
            time.sleep(retry_delay)
    raise ProviderError(f"Connection failed after {total_attempts} attempts: {last}")


def validate_draw(game_key: str, numbers: list[int], bonus: int | None) -> bool:
    """Validate a draw against the *current* game rules.

    Historical Lotto Max rows need date-aware validation because the number pool
    changed from 49 -> 50 -> 52. Use ``validate_draw_for_date`` for history.
    """
    cfg = GAMES[game_key]
    nums = [int(x) for x in numbers]
    if len(nums) != cfg.pick or len(set(nums)) != cfg.pick:
        return False
    if not all(1 <= n <= cfg.max_number for n in nums):
        return False
    if bonus is not None and (not (1 <= int(bonus) <= cfg.max_number) or int(bonus) in nums):
        return False
    return True


def historical_max_number(game_key: str, draw_date: str | date) -> int:
    """Return the legal main/bonus number ceiling for a historical draw."""
    if game_key != "max":
        return GAMES[game_key].max_number
    ds = draw_date.isoformat() if isinstance(draw_date, date) else str(draw_date)[:10]
    return int(regime_for(game_key, ds)["max_number"])


def validate_draw_for_date(game_key: str, draw_date: str | date, numbers: list[int], bonus: int | None) -> bool:
    """Validate historical data using the rules that applied on that draw date."""
    cfg = GAMES[game_key]
    nums = [int(x) for x in numbers]
    if len(nums) != cfg.pick or len(set(nums)) != cfg.pick:
        return False
    ceiling = historical_max_number(game_key, draw_date)
    if not all(1 <= n <= ceiling for n in nums):
        return False
    if bonus is not None and (not (1 <= int(bonus) <= ceiling) or int(bonus) in nums):
        return False
    return True


class LottizenProvider:
    """Structured public JSON backfill source.

    It is deliberately treated as a backfill source, not the final authority.
    Current results are cross-checked against WCLC text when possible.
    """
    BASE = "https://lottizen.com/api/v1/games"

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-CA,en;q=0.9", "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Connection": "keep-alive"})

    def _slug_candidates(self, game_key: str):
        cfg = GAMES[game_key]
        if game_key == "649":
            return [cfg.historical_slug, "lotto-6-49", "lotto-649"]
        return [cfg.historical_slug]

    def _working_slug(self, game_key: str):
        last_error = None
        for slug in dict.fromkeys(self._slug_candidates(game_key)):
            try:
                r = resilient_get(self.session, f"{self.BASE}/{slug}/latest", timeout=self.timeout)
                if r.status_code == 200 and (r.json() or {}).get("data"):
                    return slug
                last_error = f"{slug}: HTTP {r.status_code}"
            except Exception as e:
                last_error = str(e)
                logger.debug("Lottizen slug candidate failed game=%s slug=%s: %s", game_key, slug, e, exc_info=True)
        # Last-resort discovery through /games so a provider slug rename does not break V1.
        try:
            r = resilient_get(self.session, self.BASE, timeout=self.timeout)
            if r.status_code == 200:
                for g in (r.json() or {}).get("data", []):
                    name = str(g.get("name","")).lower().replace(" ","")
                    if game_key == "649" and ("6/49" in name or "649" in name):
                        return g["slug"]
                    if game_key == "max" and "lottomax" in name:
                        return g["slug"]
        except Exception as e:
            last_error = str(e)
            logger.warning("Lottizen game discovery failed game=%s: %s", game_key, e, exc_info=True)
        raise ProviderError(f"No working historical slug found ({last_error})")

    def fetch_draws(self, game_key: str, from_date: str | None = None,
                    to_date: str | None = None, max_pages: int = 20) -> list[dict]:
        slug = self._working_slug(game_key)
        out: list[dict] = []
        offset = 0
        limit = 500
        for _ in range(max_pages):
            params = {"limit": limit, "offset": offset}
            if from_date:
                params["from"] = from_date
            if to_date:
                params["to"] = to_date
            url = f"{self.BASE}/{slug}/draws"
            r = resilient_get(self.session, url, params=params, timeout=self.timeout)
            if r.status_code != 200:
                raise ProviderError(f"Historical source returned HTTP {r.status_code}")
            payload = r.json()
            data = payload.get("data") or []
            for d in data:
                nums = list(map(int, d.get("numbers") or []))
                bonus = d.get("bonus")
                bonus = int(bonus) if bonus is not None else None
                if validate_draw(game_key, nums, bonus):
                    out.append({
                        "date": d["date"],
                        "numbers": sorted(nums),
                        "bonus": bonus,
                        "source": "Lottizen API",
                        "source_url": url,
                        "raw": d,
                    })
            meta = payload.get("meta") or {}
            if not meta.get("hasMore") or not data:
                break
            offset += limit
            time.sleep(0.15)
        # de-duplicate by date, oldest first
        by_date = {d["date"]: d for d in out}
        return [by_date[k] for k in sorted(by_date)]

    def latest(self, game_key: str) -> dict | None:
        slug = self._working_slug(game_key)
        url = f"{self.BASE}/{slug}/latest"
        r = resilient_get(self.session, url, timeout=self.timeout)
        if r.status_code != 200:
            raise ProviderError(f"Latest source returned HTTP {r.status_code}")
        d = (r.json() or {}).get("data") or {}
        if not d:
            return None
        nums = list(map(int, d.get("numbers") or []))
        bonus = d.get("bonus")
        bonus = int(bonus) if bonus is not None else None
        if not validate_draw(game_key, nums, bonus):
            raise ProviderError("Latest draw failed validation")
        return {
            "date": d.get("latestDate"),
            "numbers": sorted(nums),
            "bonus": bonus,
            "source": "Lottizen API",
            "source_url": url,
            "raw": d,
        }


class WCLCOfficialValidator:
    """Cross-checks a candidate draw against WCLC's official winning-number page.

    WCLC pages are presentation HTML and may change. To avoid corrupting data when
    markup changes, this class does *not* invent a draw from partial HTML. It only
    confirms a structured candidate when the date and number sequence can be found.
    """
    MONTHS = {
        1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
        7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"
    }

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-CA,en;q=0.9", "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Connection": "keep-alive"})

    @staticmethod
    def _normalize(text: str) -> str:
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(text, "html.parser").get_text(" ")
        except Exception:
            text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip().lower()

    def verify(self, game_key: str, candidate: dict) -> bool:
        cfg = GAMES[game_key]
        try:
            r = resilient_get(self.session, cfg.official_url, timeout=self.timeout)
            if r.status_code != 200:
                return False
            text = self._normalize(r.text)
            y, m, d = map(int, candidate["date"].split("-"))
            dt = date(y, m, d)
            # Date formats commonly rendered by WCLC.
            date_tokens = [
                f"{dt.strftime('%A')}, {self.MONTHS[m]} {d:02d}, {y}".lower(),
                f"{dt.strftime('%A')}, {self.MONTHS[m]} {d}, {y}".lower(),
            ]
            if not any(tok in text for tok in date_tokens):
                return False

            # Require all main numbers plus an explicit Bonus token to be present.
            # We deliberately do not mark verified if the page cannot be confidently parsed.
            nums_ok = all(re.search(rf"(?<!\d)0?{n}(?!\d)", text) for n in candidate["numbers"])
            bonus = candidate.get("bonus")
            bonus_ok = bonus is None or re.search(rf"bonus[^0-9]{{0,80}}0?{bonus}(?!\d)", text) is not None
            return bool(nums_ok and bonus_ok)
        except Exception as e:
            logger.debug("WCLC validator failed game=%s date=%s: %s", game_key, candidate.get("date"), e, exc_info=True)
            return False

class WCLCOfficialProvider:
    """Parses the newest main draw directly from the official WCLC page."""
    DATE_RE = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$")

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-CA,en;q=0.9", "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Connection": "keep-alive"})

    def latest(self, game_key: str) -> dict:
        cfg = GAMES[game_key]
        r = resilient_get(self.session, cfg.official_url, timeout=self.timeout)
        if r.status_code != 200:
            raise ProviderError(f"WCLC returned HTTP {r.status_code}")
        try:
            from bs4 import BeautifulSoup
            lines = [s.strip() for s in BeautifulSoup(r.text, "html.parser").stripped_strings if s.strip()]
        except Exception as e:
            raise ProviderError(f"BeautifulSoup parse failed: {e}")

        date_i = None
        dt = None
        for i, line in enumerate(lines):
            m = self.DATE_RE.match(line)
            if m:
                try:
                    dt = __import__('datetime').datetime.strptime(line, "%A, %B %d, %Y").date()
                    date_i = i
                    break
                except Exception:
                    pass
        if date_i is None:
            raise ProviderError("Could not locate latest WCLC draw date")

        i = date_i + 1
        if game_key == "649":
            # Official page labels the classic-number section explicitly.
            while i < len(lines) and lines[i].upper() != "CLASSIC DRAW":
                i += 1
            if i >= len(lines):
                raise ProviderError("Could not locate CLASSIC DRAW block")
            i += 1

        nums = []
        bonus = None
        while i < len(lines) and len(nums) < cfg.pick:
            token = lines[i]
            if re.fullmatch(r"\d{1,2}", token):
                n = int(token)
                if 1 <= n <= cfg.max_number:
                    nums.append(n)
            i += 1
        # Bonus is commonly one token such as 'Bonus 47'; support split tokens too.
        for j in range(i, min(len(lines), i + 8)):
            m = re.search(r"Bonus\s*(\d{1,2})", lines[j], re.I)
            if m:
                bonus = int(m.group(1)); break
            if lines[j].lower() == "bonus" and j+1 < len(lines) and re.fullmatch(r"\d{1,2}", lines[j+1]):
                bonus = int(lines[j+1]); break
        if not validate_draw(game_key, nums, bonus):
            raise ProviderError(f"WCLC latest draw failed validation: {nums}, bonus={bonus}")
        raw = {"parsed_from":"official WCLC HTML"}
        if game_key == "649":
            joined = " | ".join(lines)
            mballs = re.search(r"(\d+)\s+Balls Remaining", joined, re.I)
            raw["gold_ball"] = {
                "balls_remaining": int(mballs.group(1)) if mballs else None,
            }
            # Locate a nearby Million value after GOLD BALL JACKPOT when available.
            try:
                gi = next(i for i,x in enumerate(lines) if "GOLD BALL JACKPOT" in x.upper())
                jackpot_m = None
                for j in range(gi+1, min(len(lines), gi+12)):
                    if re.fullmatch(r"\d{1,3}", lines[j]):
                        if j+1 < len(lines) and "Million" in lines[j+1]:
                            jackpot_m = int(lines[j]); break
                raw["gold_ball"]["jackpot_million"] = jackpot_m
            except Exception:
                raw["gold_ball"]["jackpot_million"] = None
        return {
            "date": dt.isoformat(), "numbers": sorted(nums), "bonus": bonus,
            "source": "WCLC official", "source_url": cfg.official_url,
            "raw": raw
        }


class LotoQuebecOfficialProvider:
    """Official national-game result page from Loto-Québec.

    Used as a second official source/fallback. Parsing is deliberately conservative.
    """
    URLS = {
        "max": "https://loteries.lotoquebec.com/en/lotteries/lotto-max-resultats",
        "649": "https://loteries.lotoquebec.com/en/lotteries/lotto-6-49-resultats",
    }
    DATE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})", re.I)

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-CA,en;q=0.9", "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Connection": "keep-alive"})

    @classmethod
    def parse_html(cls, game_key: str, html: str) -> dict:
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)

        if game_key == "649":
            anchor = re.search(r"The\s+Classic\s+Draw", text, re.I)
            segment = text[anchor.start():] if anchor else text
            patt = re.compile(r"((?:\d{1,2}-){5}\d{1,2})\s+Bonus\s*\(B\)\s*:?\s*\(?\s*(\d{1,2})\s*\)?", re.I)
        else:
            segment = text
            patt = re.compile(r"((?:\d{1,2}-){6}\d{1,2})\s+Bonus\s*\(B\)\s*:?\s*\(?\s*(\d{1,2})\s*\)?", re.I)
        m = patt.search(segment)
        if not m:
            raise ProviderError("Loto-Québec main result block not found")
        nums = [int(x) for x in m.group(1).split("-")]
        bonus = int(m.group(2))
        if not validate_draw(game_key, nums, bonus):
            raise ProviderError("Loto-Québec result failed validation")

        # The draw date appears before the result block. Use the nearest explicit English date.
        absolute_pos = (anchor.start() if game_key == "649" and anchor else 0) + m.start()
        prefix = text[:absolute_pos]
        dates = list(cls.DATE_RE.finditer(prefix))
        if not dates:
            raise ProviderError("Loto-Québec draw date not found")
        dm = dates[-1]
        import datetime as _dt
        dt = _dt.datetime.strptime(dm.group(0), "%B %d, %Y").date()
        return {
            "date": dt.isoformat(), "numbers": sorted(nums), "bonus": bonus,
            "source": "Loto-Québec official", "source_url": cls.URLS[game_key],
            "raw": {"parsed_from": "official Loto-Québec HTML"},
        }

    def latest(self, game_key: str) -> dict:
        url = self.URLS[game_key]
        r = resilient_get(self.session, url, timeout=self.timeout)
        if r.status_code != 200:
            raise ProviderError(f"Loto-Québec returned HTTP {r.status_code}")
        return self.parse_html(game_key, r.text)


class AtlanticLotteryOfficialVerifier:
    """Official Atlantic Lottery page used as an independent cross-check.

    ALC's public page may not expose a stable draw-date token in the same result block,
    so this provider verifies a candidate's main numbers + bonus rather than inventing a date.
    """
    URL = "https://www.alc.ca/content/alc/en/winning-numbers.html"

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-CA,en;q=0.9", "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Connection": "keep-alive"})

    def verify(self, game_key: str, candidate: dict) -> bool:
        try:
            r = resilient_get(self.session, self.URL, timeout=self.timeout)
            if r.status_code != 200:
                return False
            try:
                from bs4 import BeautifulSoup
                lines = [x.strip() for x in BeautifulSoup(r.text, "html.parser").stripped_strings if x.strip()]
                text = " | ".join(lines)
            except Exception:
                text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
            label = "CLASSIC DRAW" if game_key == "649" else "MAIN DRAW"
            pos = text.upper().find(label)
            if pos < 0:
                return False
            # Limit to the nearby game block so numbers from other games do not create a false match.
            seg = text[pos:pos+1200]
            nums_ok = all(re.search(rf"(?<!\d)0?{int(n)}(?!\d)", seg) for n in candidate["numbers"])
            b = candidate.get("bonus")
            bonus_ok = b is None or re.search(rf"BONUS[^0-9]{{0,120}}0?{int(b)}(?!\d)", seg, re.I)
            return bool(nums_ok and bonus_ok)
        except Exception as e:
            logger.debug("Atlantic Lottery verifier failed game=%s date=%s: %s", game_key, candidate.get("date"), e, exc_info=True)
            return False


class WCLCOfficialHistoryProvider(WCLCOfficialProvider):
    """Conservative parser for the multiple past draws rendered on WCLC official pages."""
    def fetch_recent_draws(self, game_key: str) -> list[dict]:
        cfg = GAMES[game_key]
        r = resilient_get(self.session, cfg.official_url, timeout=self.timeout)
        if r.status_code != 200:
            raise ProviderError(f"WCLC history returned HTTP {r.status_code}")
        try:
            from bs4 import BeautifulSoup
            lines = [s.strip() for s in BeautifulSoup(r.text, "html.parser").stripped_strings if s.strip()]
        except Exception as e:
            raise ProviderError(f"WCLC history parse failed: {e}")
        out=[]
        import datetime as _dt
        i=0
        while i < len(lines):
            if not self.DATE_RE.match(lines[i]):
                i += 1; continue
            try:
                dt=_dt.datetime.strptime(lines[i], "%A, %B %d, %Y").date()
            except Exception:
                i += 1; continue
            j=i+1
            if game_key == "649":
                while j < min(len(lines), i+80) and lines[j].upper() != "CLASSIC DRAW" and not self.DATE_RE.match(lines[j]):
                    j += 1
                if j >= len(lines) or lines[j].upper() != "CLASSIC DRAW":
                    i += 1; continue
                j += 1
            nums=[]; bonus=None
            while j < min(len(lines), i+120) and len(nums) < cfg.pick:
                if self.DATE_RE.match(lines[j]): break
                if re.fullmatch(r"\d{1,2}", lines[j]):
                    n=int(lines[j])
                    if 1 <= n <= cfg.max_number:
                        nums.append(n)
                j += 1
            for k in range(j, min(len(lines), j+12)):
                m=re.search(r"Bonus\s*(\d{1,2})", lines[k], re.I)
                if m:
                    bonus=int(m.group(1)); break
                if lines[k].lower()=="bonus" and k+1 < len(lines) and re.fullmatch(r"\d{1,2}", lines[k+1]):
                    bonus=int(lines[k+1]); break
            if validate_draw(game_key, nums, bonus):
                out.append({"date":dt.isoformat(),"numbers":sorted(nums),"bonus":bonus,
                            "source":"WCLC official history","source_url":cfg.official_url,
                            "raw":{"parsed_from":"official WCLC past winning numbers"}})
            i += 1
        by={d['date']:d for d in out}
        return [by[k] for k in sorted(by)]


class WCLCSinceInceptionProvider:
    """Official WCLC full-history archive for both national games.

    WCLC currently exposes the since-inception files as PDF-like downloads. The
    parser only accepts rows that pass date-aware lottery validation. The archive
    is also used as the canonical draw-date calendar when available, preventing
    false missing/extra flags caused by hard-coded schedule assumptions.
    """
    URLS = {
        "649": "https://www.wclc.com/display-on/display-on-downloads/lotto-649-since-inception.htm?channel=print",
        "max": "https://www.wclc.com/display-on/display-on-downloads/lotto-max-since-inception.htm",
    }
    URL_CANDIDATES = {
        "649": [
            "https://www.wclc.com/display-on/display-on-downloads/lotto-649-since-inception.htm?channel=print",
            "https://www.wclc.com/display-on/display-on-downloads/lotto-649-since-inception.htm",
        ],
        "max": [
            "https://www.wclc.com/display-on/display-on-downloads/lotto-max-since-inception.htm",
        ],
    }
    DATE_RE = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s*(\d{4})", re.I
    )

    def __init__(self, timeout=40):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "application/pdf,text/html,*/*"})

    @classmethod
    def parse_html_table(cls, game_key: str, html: str, source_url: str = "") -> list[dict]:
        """Parse WCLC's since-inception HTML table directly.

        The download endpoint currently renders rows as:
        date | winning numbers | bonus | EXTRA.  Parsing cells directly is much
        more reliable than flattening the whole page into text because unrelated
        page numbers/EXTRA values cannot slide into the winning-number window.
        """
        try:
            from bs4 import BeautifulSoup
        except Exception:
            return []
        cfg = GAMES[game_key]
        soup = BeautifulSoup(str(html or ""), "html.parser")
        out = []
        for tr in soup.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            try:
                dt = datetime.strptime(cells[0].strip(), "%B %d, %Y").date()
            except Exception:
                continue
            nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", cells[1])]
            bonus_vals = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", cells[2])]
            if len(nums) != cfg.pick or not bonus_vals:
                continue
            bonus = bonus_vals[0]
            if not validate_draw_for_date(game_key, dt, nums, bonus):
                continue
            out.append({
                "date": dt.isoformat(), "numbers": sorted(nums), "bonus": bonus,
                "source": "WCLC official since inception", "source_url": source_url,
                "verified": True,
                "raw": {"history_provider": "wclc_since_inception", "parser": "html_table"},
            })
        by = {d["date"]: d for d in out}
        return [by[k] for k in sorted(by)]

    @classmethod
    def parse_text(cls, game_key: str, text: str, source_url: str = "") -> list[dict]:
        cfg = GAMES[game_key]
        text = str(text or "")
        out = []

        # Fast/safe path for WCLC PDF extraction: most official rows are emitted as
        # one physical text line: "Month D, YYYY n1 n2 ... bonus ...". Parsing the
        # seven draw tokens from that same line avoids interference from GPD/EXTRA,
        # page headers, and the many Gold Ball/Super Draw serial-number lines.
        for line in text.splitlines():
            m = cls.DATE_RE.search(line)
            if not m:
                continue
            try:
                dt = datetime.strptime(m.group(0).replace(",", ", ").replace(",  ", ", "), "%B %d, %Y").date()
            except Exception:
                # Be tolerant of PDFs that omit the space after the comma.
                try:
                    dt = datetime.strptime(re.sub(r",\s*", ", ", m.group(0)), "%B %d, %Y").date()
                except Exception:
                    continue
            tail = line[m.end():]
            vals = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", tail)]
            if len(vals) < cfg.pick + 1:
                continue
            nums = vals[:cfg.pick]
            bonus = vals[cfg.pick]
            if not validate_draw_for_date(game_key, dt, nums, bonus):
                continue
            out.append({
                "date": dt.isoformat(), "numbers": sorted(nums), "bonus": bonus,
                "source": "WCLC official since inception", "source_url": source_url,
                "verified": True,
                "raw": {"history_provider": "wclc_since_inception", "parser": "pdf_line"},
            })

        # Block fallback fills rows whose PDF layout wrapped the winning numbers onto
        # a following line. Existing line-parsed dates win when both paths succeed.
        matches = list(cls.DATE_RE.finditer(text))
        for i, m in enumerate(matches):
            try:
                dt = datetime.strptime(re.sub(r",\s*", ", ", m.group(0)), "%B %d, %Y").date()
            except Exception:
                continue
            end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), m.end() + 500)
            block = text[m.end():end]
            vals = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", block)]
            if len(vals) < cfg.pick + 1:
                continue
            chosen = None
            for off in range(0, min(8, max(1, len(vals) - cfg.pick))):
                nums = vals[off:off + cfg.pick]
                bonus = vals[off + cfg.pick] if off + cfg.pick < len(vals) else None
                if validate_draw_for_date(game_key, dt, nums, bonus):
                    chosen = (sorted(nums), bonus)
                    break
            if not chosen:
                continue
            nums, bonus = chosen
            out.append({
                "date": dt.isoformat(), "numbers": nums, "bonus": bonus,
                "source": "WCLC official since inception", "source_url": source_url,
                "verified": True,
                "raw": {"history_provider": "wclc_since_inception", "parser": "pdf_block"},
            })
        by = {d["date"]: d for d in out}
        return [by[k] for k in sorted(by)]

    def fetch_all(self, game_key: str) -> list[dict]:
        errors = []
        for url in self.URL_CANDIDATES.get(game_key, [self.URLS[game_key]]):
            try:
                r = resilient_get(self.session, url, timeout=self.timeout, retries=3)
                if r.status_code != 200:
                    raise ProviderError(f"HTTP {r.status_code}")
                content = r.content or b""
                ctype = str(r.headers.get("Content-Type", "")).lower()
                text = ""
                if content.startswith(b"%PDF") or "pdf" in ctype:
                    try:
                        from io import BytesIO
                        from pypdf import PdfReader
                        reader = PdfReader(BytesIO(content))
                        chunks = []
                        for page in reader.pages:
                            try:
                                t = page.extract_text(extraction_mode="layout") or ""
                            except Exception:
                                t = page.extract_text() or ""
                            chunks.append(t)
                        text = "\n".join(chunks)
                    except Exception as e:
                        raise ProviderError(f"PDF parse failed: {e}")
                else:
                    rows = self.parse_html_table(game_key, r.text, url)
                    if rows:
                        return rows
                    try:
                        from bs4 import BeautifulSoup
                        text = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)
                    except Exception:
                        text = r.text
                rows = self.parse_text(game_key, text, url)
                if rows:
                    return rows
                raise ProviderError("archive yielded no valid draw rows")
            except Exception as e:
                errors.append(f"{url}: {e}")
                logger.warning("WCLC archive source failed game=%s url=%s: %s", game_key, url, e, exc_info=True)
        raise ProviderError("; ".join(errors[:3]) or "WCLC since-inception archive failed")


class NationalLottery649HistoryProvider:
    """Third-party archive fallback for Lotto 6/49 only.

    Never marks records verified. It is used only when the primary structured archive is
    unavailable; newest draws are still cross-checked against official Canadian sources.
    """
    BASE = "https://www.national-lottery.com/canada-6-49/results/{year}-archive"
    DATE_RE = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})$")

    def __init__(self, timeout=20):
        self.timeout=timeout
        self.session=requests.Session()
        self.session.headers.update({"User-Agent":UA})

    def fetch_all(self, start_year=1982, end_year=None):
        import datetime as _dt
        end_year=end_year or _dt.date.today().year
        out=[]
        for year in range(end_year, start_year-1, -1):
            url=self.BASE.format(year=year)
            r=resilient_get(self.session, url, timeout=self.timeout)
            if r.status_code != 200:
                logger.debug("National-Lottery archive returned HTTP %s year=%s url=%s", r.status_code, year, url)
                continue
            try:
                from bs4 import BeautifulSoup
                lines=[x.strip() for x in BeautifulSoup(r.text,"html.parser").stripped_strings if x.strip()]
            except Exception as e:
                logger.debug("National-Lottery archive parse failed year=%s url=%s: %s", year, url, e, exc_info=True)
                continue
            i=0
            while i < len(lines):
                m=self.DATE_RE.match(lines[i])
                if not m:
                    i+=1; continue
                try:
                    dt=_dt.datetime.strptime(lines[i],"%A %B %d %Y").date()
                except Exception:
                    i+=1; continue
                nums=[]; j=i+1
                while j < min(len(lines),i+35) and len(nums)<7:
                    if self.DATE_RE.match(lines[j]): break
                    if re.fullmatch(r"\d{1,2}",lines[j]):
                        n=int(lines[j])
                        if 1<=n<=49: nums.append(n)
                    j+=1
                if len(nums)>=7 and validate_draw("649",nums[:6],nums[6]):
                    out.append({"date":dt.isoformat(),"numbers":sorted(nums[:6]),"bonus":nums[6],
                                "source":"National-Lottery archive fallback","source_url":url,
                                "raw":{"archive_year":year}})
                i+=1
            time.sleep(.05)
        by={d['date']:d for d in out}
        return [by[k] for k in sorted(by)]


class OLGOfficialProvider:
    """Second official national-result source from OLG's static Chinese results page.

    The national Lotto Max / Lotto 6/49 numbers are the same across Canada. This
    page is useful as a fallback because its result text is server-rendered rather
    than depending on the JavaScript blocks used by some other lottery sites.
    """
    URL = "https://chinese.olg.ca/sc/index.php"

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en-CA;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Connection": "keep-alive",
        })

    @classmethod
    def parse_html(cls, game_key: str, html: str) -> dict:
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        # Restrict parsing to the winning-numbers area where possible.
        marker = text.find("至爱游戏")
        if marker >= 0:
            text = text[marker:]
        cfg = GAMES[game_key]
        label = r"Lotto\s*Max" if game_key == "max" else r"LOTTO\s*(?:6/?49|649)"
        numpat = r"(\d{1,2}(?:\s*,\s*\d{1,2}){%d})" % (cfg.pick - 1)
        patt = re.compile(
            label + r".*?中奖号码\s*(\d{4})年(\d{1,2})月(\d{1,2})日.*?" +
            numpat + r".*?特别号码\s*(\d{1,2})",
            re.I | re.S,
        )
        m = patt.search(text)
        if not m:
            raise ProviderError("OLG official result block not found")
        y, mo, d = map(int, m.group(1, 2, 3))
        nums = [int(x.strip()) for x in m.group(4).split(",")]
        bonus = int(m.group(5))
        if not validate_draw(game_key, nums, bonus):
            raise ProviderError(f"OLG result failed validation: {nums}, bonus={bonus}")
        return {
            "date": date(y, mo, d).isoformat(),
            "numbers": sorted(nums),
            "bonus": bonus,
            "source": "OLG official",
            "source_url": cls.URL,
            "raw": {"parsed_from": "official OLG static results page"},
        }

    def latest(self, game_key: str) -> dict:
        r = resilient_get(self.session, self.URL, timeout=self.timeout)
        if r.status_code != 200:
            raise ProviderError(f"OLG returned HTTP {r.status_code}")
        return self.parse_html(game_key, r.text)


class LottoDatabaseHistoryProvider:
    """Year-by-year historical archive for both Canadian national games.

    This is a non-official recovery source. Records are always validated and are
    never allowed to overwrite an already official-verified draw with unverified
    data. The current official result is still sourced from WCLC/OLG.
    """
    SLUGS = {"649": "lotto-649", "max": "lotto-max"}
    BASE = "https://www.lottodatabase.com/lotto-database/canadian-lotteries/{slug}/draw-history/{year}"
    DATE_RE = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s+(\d{4})",
        re.I,
    )

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-CA,en;q=0.9"})

    @classmethod
    def parse_html(cls, game_key: str, html: str, source_url: str = "") -> list[dict]:
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        cfg = GAMES[game_key]
        matches = list(cls.DATE_RE.finditer(text))
        out = []
        import datetime as _dt
        for idx, m in enumerate(matches):
            end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(text), m.end() + 700)
            seg = text[m.end():end]
            # The archive prints the main numbers followed immediately by the bonus.
            vals = [int(x) for x in re.findall(r"(?<![\d$,])\d{1,2}(?!\d)", seg)]
            need = cfg.pick + 1
            found = None
            for s in range(0, max(1, min(8, len(vals) - need + 1))):
                cand = vals[s:s + need]
                if len(cand) == need and validate_draw(game_key, cand[:cfg.pick], cand[cfg.pick]):
                    found = cand
                    break
            if not found:
                continue
            try:
                dt = _dt.datetime.strptime(m.group(0), "%A, %B %d, %Y").date()
            except Exception:
                continue
            out.append({
                "date": dt.isoformat(), "numbers": sorted(found[:cfg.pick]), "bonus": found[cfg.pick],
                "source": "LottoDatabase historical archive", "source_url": source_url,
                "raw": {"history_provider": "lottodatabase"},
            })
        by = {d["date"]: d for d in out}
        return [by[k] for k in sorted(by)]

    def fetch_year(self, game_key: str, year: int) -> list[dict]:
        url = self.BASE.format(slug=self.SLUGS[game_key], year=int(year))
        r = resilient_get(self.session, url, timeout=self.timeout)
        if r.status_code != 200:
            raise ProviderError(f"LottoDatabase {year} returned HTTP {r.status_code}")
        return self.parse_html(game_key, r.text, url)

    def fetch_years(self, game_key: str, years: Iterable[int], progress=None) -> list[dict]:
        years = sorted(set(map(int, years)))
        out = []
        errors = []
        for i, y in enumerate(years, 1):
            try:
                out.extend(self.fetch_year(game_key, y))
            except Exception as e:
                errors.append(f"{y}: {e}")
                logger.warning("LottoDatabase history failed game=%s year=%s: %s", game_key, y, e, exc_info=True)
            if progress:
                progress(i, len(years))
            time.sleep(0.08)
        if not out and errors:
            raise ProviderError("; ".join(errors[:5]))
        by = {d["date"]: d for d in out}
        return [by[k] for k in sorted(by)]


class LottoNetHistoryProvider:
    """Secondary non-official yearly archive used to repair holes/confirm history."""
    SLUGS = {"649": "canada-lotto-6-49", "max": "canada-lotto-max"}
    BASE = "https://www.lotto.net/{slug}/numbers/{year}"
    DATE_RE = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})",
        re.I,
    )

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-CA,en;q=0.9"})

    @classmethod
    def parse_html(cls, game_key: str, html: str, source_url: str = "") -> list[dict]:
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        cfg = GAMES[game_key]
        matches = list(cls.DATE_RE.finditer(text))
        out = []
        import datetime as _dt
        for idx, m in enumerate(matches):
            end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(text), m.end() + 900)
            seg = text[m.end():end]
            # Jackpot strings contain commas/$ and therefore do not match this standalone token pattern.
            vals = [int(x) for x in re.findall(r"(?<![\d$,])\d{1,2}(?!\d)", seg)]
            need = cfg.pick + 1
            found = None
            for s in range(0, max(1, min(8, len(vals) - need + 1))):
                cand = vals[s:s + need]
                if len(cand) == need and validate_draw(game_key, cand[:cfg.pick], cand[cfg.pick]):
                    found = cand
                    break
            if not found:
                continue
            clean_date = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", m.group(0), flags=re.I)
            try:
                dt = _dt.datetime.strptime(clean_date, "%A %B %d %Y").date()
            except Exception:
                continue
            out.append({
                "date": dt.isoformat(), "numbers": sorted(found[:cfg.pick]), "bonus": found[cfg.pick],
                "source": "Lotto.net historical archive", "source_url": source_url,
                "raw": {"history_provider": "lotto.net"},
            })
        by = {d["date"]: d for d in out}
        return [by[k] for k in sorted(by)]

    def fetch_year(self, game_key: str, year: int) -> list[dict]:
        url = self.BASE.format(slug=self.SLUGS[game_key], year=int(year))
        r = resilient_get(self.session, url, timeout=self.timeout)
        if r.status_code != 200:
            raise ProviderError(f"Lotto.net {year} returned HTTP {r.status_code}")
        return self.parse_html(game_key, r.text, url)

    def fetch_years(self, game_key: str, years: Iterable[int], progress=None) -> list[dict]:
        years = sorted(set(map(int, years)))
        out = []
        errors = []
        for i, y in enumerate(years, 1):
            try:
                out.extend(self.fetch_year(game_key, y))
            except Exception as e:
                errors.append(f"{y}: {e}")
                logger.debug("Lotto.net history failed game=%s year=%s: %s", game_key, y, e, exc_info=True)
            if progress:
                progress(i, len(years))
            time.sleep(0.08)
        if not out and errors:
            raise ProviderError("; ".join(errors[:5]))
        by = {d["date"]: d for d in out}
        return [by[k] for k in sorted(by)]


class GitHubCsvHistoryProvider:
    """Multi-repository GitHub CSV recovery layer.

    GitHub is intentionally *not* an official authority. All GitHub repositories
    share one logical source label so mirrors/copies cannot create fake consensus.
    Conflicting GitHub rows for the same date are held out rather than guessed.
    """

    SOURCES = {
        "649": [
            {"name": "lotto88ai/lotto-data",
             "url": "https://raw.githubusercontent.com/lotto88ai/lotto-data/main/649.csv"},
            {"name": "DavidZhang-2022/Lotto649",
             "url": "https://raw.githubusercontent.com/DavidZhang-2022/Lotto649/main/lotto_649_complete.csv"},
            {"name": "sch2000/Lotto-Result",
             "url": "https://raw.githubusercontent.com/sch2000/Lotto-Result/master/Lotto649.csv"},
        ],
        "max": [
            {"name": "medikid/lotto",
             "url": "https://raw.githubusercontent.com/medikid/lotto/master/sites/all/modules/custom/lotto/lotto_import_export/data/LOTTOMAX.csv"},
            {"name": "msubin/webscraper_lotto_max",
             "url": "https://raw.githubusercontent.com/msubin/webscraper_lotto_max/master/lottoMax_results.csv"},
            {"name": "sch2000/Lotto-Result",
             "url": "https://raw.githubusercontent.com/sch2000/Lotto-Result/master/LottoMax.csv"},
        ],
    }

    def __init__(self, timeout=25):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "text/csv,text/plain,*/*"})
        self.last_report = {}

    @staticmethod
    def _norm_header(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    @staticmethod
    def _scheduled_date(game_key: str, dt: date) -> bool:
        if game_key == "649":
            if dt < date(1985, 9, 11):
                return dt.weekday() == 5  # Saturday only in the original era
            return dt.weekday() in (2, 5)  # Wednesday / Saturday
        if dt < date(2019, 5, 14):
            return dt.weekday() == 4       # Friday
        return dt.weekday() in (1, 4)      # Tuesday / Friday

    @classmethod
    def identity_audit(cls, game_key: str, rows: list[dict]) -> dict:
        """Detect datasets that merely share the '6/49' name with Canada's game.

        This intentionally uses calendar compatibility as a gate, not as proof of
        correctness.  It catches common contamination such as Philippine Super
        Lotto 6/49 (Tue/Thu/Sun) before those rows can enter consensus history.
        """
        if not rows:
            return {"status": "REJECT", "compatibility_pct": 0.0, "off_schedule": 0, "samples": []}
        off = []
        plus_one = []
        for d in rows:
            try:
                dt = date.fromisoformat(d["date"])
            except Exception:
                off.append(str(d.get("date")))
                continue
            if not cls._scheduled_date(game_key, dt):
                off.append(dt.isoformat())
                if cls._scheduled_date(game_key, dt - timedelta(days=1)):
                    plus_one.append(dt.isoformat())
        pct = 100.0 * (len(rows) - len(off)) / max(1, len(rows))
        # A genuine Canadian history source should be overwhelmingly compatible.
        # We keep a small tolerance for source transcription quirks, but the bad
        # rows themselves are held out unless an official calendar later proves them.
        status = "PASS" if pct >= 99.0 else ("WARN" if pct >= 97.0 else "REJECT")
        return {
            "status": status, "compatibility_pct": round(pct, 3),
            "off_schedule": len(off), "samples": off[:12],
            "plus_one_shift_candidates": len(plus_one),
        }

    @classmethod
    def _parse_date(cls, raw: str) -> date | None:
        raw = re.sub(r"\s+", " ", str(raw or "").strip())
        if not raw:
            return None
        formats = (
            "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y",
            "%B %d, %Y", "%b %d, %Y",
            "%Y-%b-%d %A", "%Y-%B-%d %A",
            "%Y%m%d",
        )
        for fmt in formats:
            try:
                return datetime.strptime(raw, fmt).date()
            except Exception:
                pass
        # Some CSVs append a weekday after an otherwise parseable date.
        raw2 = re.sub(r"\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)$", "", raw, flags=re.I)
        if raw2 != raw:
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
                try:
                    return datetime.strptime(raw2, fmt).date()
                except Exception:
                    pass
        return None

    @classmethod
    def parse_csv(cls, game_key: str, text: str, source_name: str, source_url: str = "") -> list[dict]:
        import ast
        import csv as _csv
        import io as _io

        reader = _csv.DictReader(_io.StringIO(text.lstrip("\ufeff")))
        cfg = GAMES[game_key]
        out = []
        for row in reader:
            norm = {cls._norm_header(k): v for k, v in row.items() if k is not None}
            # Official-style exports can include MAXMILLIONS/secondary sequences.
            # Sequence 0 is the actual main draw; non-zero sequences are not history rows for this model.
            seq = norm.get("sequencenumber")
            if seq not in (None, ""):
                try:
                    if int(float(str(seq).strip())) != 0:
                        continue
                except Exception:
                    pass
            raw_date = (norm.get("playdate") or norm.get("date") or
                        norm.get("drawdate") or norm.get("resultdate") or "")
            dt = cls._parse_date(raw_date)
            if not dt:
                continue

            nums = []
            for i in range(1, cfg.pick + 1):
                val = (norm.get(f"no{i}") or norm.get(f"num{i}") or
                       norm.get(f"n{i}") or norm.get(f"numberdrawn{i}"))
                if val in (None, ""):
                    nums = []
                    break
                try:
                    nums.append(int(float(str(val).strip())))
                except Exception:
                    nums = []
                    break

            # msubin stores all seven Lotto Max numbers in one Python-list-like cell.
            if not nums:
                packed = norm.get("numbers") or norm.get("winningnumbers")
                if packed:
                    try:
                        obj = ast.literal_eval(str(packed))
                        vals = list(obj) if isinstance(obj, (list, tuple)) else []
                        nums = [int(str(x).strip()) for x in vals[:cfg.pick]]
                    except Exception:
                        vals = re.findall(r"(?<!\d)\d{1,2}(?!\d)", str(packed))
                        nums = [int(x) for x in vals[:cfg.pick]]

            bonus_raw = norm.get("bonus") or norm.get("bonusnumber")
            try:
                bonus = int(float(str(bonus_raw).strip()))
            except Exception:
                continue

            if validate_draw_for_date(game_key, dt, nums, bonus):
                out.append({
                    "date": dt.isoformat(), "numbers": sorted(nums), "bonus": bonus,
                    "source": "GitHub historical recovery", "source_url": source_url,
                    "raw": {"history_provider": "github", "github_repo": source_name},
                })
        by = {d["date"]: d for d in out}
        return [by[k] for k in sorted(by)]

    @staticmethod
    def _fingerprint(d: dict):
        return tuple(sorted(map(int, d.get("numbers", [])))), int(d.get("bonus"))

    def fetch_all(self, game_key: str) -> list[dict]:
        all_rows = []
        self.last_report = {}
        for spec in self.SOURCES[game_key]:
            name, url = spec["name"], spec["url"]
            try:
                r = resilient_get(self.session, url, timeout=self.timeout, retries=2)
                if r.status_code != 200:
                    raise ProviderError(f"HTTP {r.status_code}")
                rows = self.parse_csv(game_key, r.text, name, url)
                audit = self.identity_audit(game_key, rows)
                # Off-calendar third-party rows are never allowed to create a
                # Canadian draw by themselves. Official WCLC history remains the
                # authority for any true exceptional date.
                clean_rows = []
                for d in rows:
                    try:
                        dt = date.fromisoformat(d["date"])
                    except Exception:
                        continue
                    if self._scheduled_date(game_key, dt):
                        clean_rows.append(d)
                accepted = clean_rows if audit["status"] != "REJECT" else []
                self.last_report[name] = {
                    "ok": bool(accepted), "draws": len(accepted), "parsed_draws": len(rows),
                    "url": url, "identity_gate": audit["status"],
                    "calendar_compatibility_pct": audit["compatibility_pct"],
                    "off_schedule_filtered": audit["off_schedule"],
                    "off_schedule_sample": audit["samples"],
                    "plus_one_shift_candidates": audit["plus_one_shift_candidates"],
                }
                if audit["status"] == "REJECT":
                    self.last_report[name]["error"] = "Dataset identity gate rejected calendar pattern"
                elif not accepted:
                    self.last_report[name]["error"] = "No Canadian-schedule rows accepted"
                all_rows.extend(accepted)
            except Exception as e:
                self.last_report[name] = {"ok": False, "error": str(e), "url": url}
                logger.warning("GitHub history source failed game=%s source=%s: %s", game_key, name, e, exc_info=True)

        if not all_rows:
            errors = "; ".join(f"{k}: {v.get('error','no data')}" for k, v in self.last_report.items())
            raise ProviderError(f"No GitHub history source returned usable rows ({errors})")

        grouped = {}
        for d in all_rows:
            grouped.setdefault(d["date"], []).append(d)
        merged = []
        conflicts = 0
        for draw_date, rows in sorted(grouped.items()):
            fps = {}
            for d in rows:
                fps.setdefault(self._fingerprint(d), []).append(d)
            if len(fps) != 1:
                conflicts += 1
                continue
            agreed = next(iter(fps.values()))
            chosen = dict(agreed[0])
            repos = sorted({r.get("raw", {}).get("github_repo") for r in agreed if r.get("raw", {}).get("github_repo")})
            chosen["raw"] = {
                "history_provider": "github",
                "github_repos": repos,
                "github_agreement_count": len(repos),
            }
            merged.append(chosen)
        self.last_report["_summary"] = {
            "ok": bool(merged), "draws": len(merged), "conflicts_held_out": conflicts,
        }
        return merged
