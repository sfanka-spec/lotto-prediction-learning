from __future__ import annotations

import json
import logging
import queue
from logging.handlers import RotatingFileHandler
import threading
import traceback
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from lottery_ai.backtest import (walk_forward_test, shuffle_test, null_synthetic_test, random_control_walk_forward,
                                feature_ablation_test, rank_stability_test, coverage_strategy_backtest,
                                bayesian_strategy_walk_forward)
from lottery_ai.config import (APP_NAME, APP_VERSION, GAMES, DEFAULT_CANDIDATES, BONUS_WEIGHTS, normalize_main_weights,
    RANDOM_CONTROL_VERSION, RESEARCH_PORTFOLIO_VERSION, RESEARCH_PORTFOLIO_SIZE,
    V14_STRATEGY_VERSIONS, V14_STRATEGY_PREFIXES,
    PORTFOLIO_POLICY_VERSION, PORTFOLIO_DEFAULT_BUDGETS, PORTFOLIO_PROVISIONAL_N,
    PREDICTION_CUTOFF_HOUR, PREDICTION_CUTOFF_MINUTE)
from lottery_ai.db import Database
from lottery_ai.engine import PredictionEngine
from lottery_ai.coverage import coverage_summary, overlap_matrix
from lottery_ai.research_engine import (RandomControlEngine, ResearchPortfolioOptimizer,
    portfolio_summary, stable_seed)
from lottery_ai.regime import regime_summary
from lottery_ai.learning import LearningManager, next_draw_date
from lottery_ai.models import NeuralShadow, RegionNeuralShadow
from lottery_ai.updater import DataUpdater, era_for
from lottery_ai.paths import resolve_data_dir
from lottery_ai.analysis import exact_sum_distribution, exact_span_distribution, central_interval, paired_z_score, paired_t_critical_95
from lottery_ai.timeutil import pacific_now
from lottery_ai.bonus import (build_bonus_payload, normalize_bonus_payload, bonus_top_for_pick,
    main_bonus_consistency)
from lottery_ai.presentation import build_current_draw_snapshot, format_bc_timestamp
from lottery_ai.champion import (summarize_champion_records, CHAMPION_CALIBRATION_MIN_SAMPLES,
    classify_rank_association)
from lottery_ai.evaluation import strategy_validation_summary
from lottery_ai.integrity import build_freeze_integrity, verify_freeze_integrity, sha256_json
from lottery_ai.portfolio import (PortfolioOptimizer, learn_shadow_policy, portfolio_validation_summary, portfolio_phase, budget_frontier_learning, line_selection_learning)
from lottery_ai.jackpot import jackpot_economics
from lottery_ai.bayesian_strategy import (
    forward_strategy_observations, hierarchical_strategy_posterior,
)

BASE = Path(__file__).resolve().parent
DATA_DIR = resolve_data_dir(BASE)
DB_PATH = DATA_DIR / "lottery.db"
MODEL_DIR = DATA_DIR / "models"
SEED_PATH = BASE / "data" / "seed_recent.json"

def _configure_file_logging():
    """Best-effort rotating diagnostics under the selected persistent data folder."""
    try:
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        root_logger = logging.getLogger()
        target = str((log_dir / "lottery_ai.log").resolve())
        if not any(getattr(h, "baseFilename", None) == target for h in root_logger.handlers):
            handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            handler.setLevel(logging.INFO)
            root_logger.addHandler(handler)
        if root_logger.level > logging.INFO:
            root_logger.setLevel(logging.INFO)
    except Exception:
        pass  # diagnostics must never prevent startup

_configure_file_logging()
logger = logging.getLogger(__name__)

UI_TEXT = {
    "top_picks": ("TOP PICKS", "首选组合"),
    "coverage_optimized_picks": ("COVERAGE OPTIMIZED PICKS", "覆盖优化组合"),
    "coverage": ("Coverage", "覆盖优化"),
    "budget": ("Budget AI", "预算AI"),
    "jackpot": ("Jackpot", "奖池"),
    "portfolio_value": ("Portfolio Value", "组合包价值"),
    "main": ("Main", "主号"),
    "bonus": ("Bonus", "特别号"),
    "goldball": ("Gold Ball", "金球"),
    "weights": ("Weights", "权重"),
    "learning": ("Learning", "学习"),
    "research": ("Research", "研究"),
    "data": ("Data", "数据"),
    "analysis": ("Analysis", "分析"),
    "show_top_10": ("Show Top 10", "显示前10"),
    "show_top_20": ("Show Top 20", "显示前20"),
    "show_top_3": ("Show Top 3", "显示前3"),
    "generate": ("Generate Official Prediction", "生成正式预测"),
    "update_before": ("Update Data Before Prediction", "预测前请先更新数据"),
    "prediction_frozen": ("Prediction Frozen", "预测已冻结"),
    "official_locked": ("Official prediction locked", "正式预测已锁定"),
    "combination_score": ("Combination Score", "组合评分"),
    "bonus_conditional_score": ("Bonus Conditional Score", "特别号条件评分"),
    "crowd": ("Sharing Risk", "共享风险"),
    "based_on_pick": ("Based on Main Pick", "基于主号组合"),
    "not_comparable": ("Bonus Conditional Score is not directly comparable with Main Combination Score.",
                       "特别号条件评分不能与主号组合评分直接比较。"),
    "language": ("Language", "语言"),
    "update_now": ("Update Data Now", "立即更新数据"),
    "auto_promotion": ("Auto Promotion (strict gate)", "自动晋级（严格门槛）"),
    "freeze_shadow": ("Freeze V1.4 Validation Suite", "冻结 V1.4 验证研究组"),
    "run_research": ("Run Research + Bayesian Lab", "运行研究＋贝叶斯实验室"),
    "refresh_repair": ("Refresh Official Calendar + Repair", "刷新官方日历并修复"),
    "run_audit": ("Run Integrity Audit", "运行完整性审计"),
    "import_csv": ("Import History CSV", "导入历史 CSV"),
    "binding_mode": ("Binding mode", "绑定模式"),
    "main_combo": ("Main combination", "主号组合"),
    "bonus_independent": ("Each Main Pick has its own independently frozen Bonus ranking; Main numbers are excluded automatically.",
                           "每一组主号都有自己独立冻结的特别号排名，并自动排除该组主号。"),
    "bonus_missing_legacy": ("No frozen Bonus ranking exists for this Main Pick in the legacy prediction. It is intentionally NOT backfilled with later data.",
                             "旧版冻结预测没有为此主号组合保存特别号排名；为防止未来数据泄漏，系统不会用后来的数据回填。"),
    "bonus_missing": ("No frozen Bonus ranking is available for this Main Pick.", "此主号组合暂无冻结的特别号排名。"),
    "bonus_immutable": ("Frozen Bonus rankings are immutable after the prediction cutoff.", "预测数据截止后，已冻结的特别号排名保持不可变。"),
    "legacy_pick1": ("LEGACY FROZEN · PICK #1 ONLY", "旧版冻结 · 仅第1组主号"),
    "v11_per_main": ("V1.1+ FROZEN PER-MAIN", "V1.1+ 按主号逐组冻结"),
    "current_draw": ("CURRENT DRAW", "当期开奖"),
    "next_draw": ("NEXT DRAW", "下一期开奖"),
    "partial_frozen": ("PARTIAL FROZEN BINDING", "部分冻结绑定"),
    "frozen_error": ("FROZEN CONSISTENCY ERROR", "冻结一致性错误"),
}

LANG_LABELS = {"bilingual":"中英双语", "en":"English", "zh":"中文"}


def fmt_numbers(nums):
    return "  ".join(f"{int(n):02d}" for n in nums)


class CollapsibleGameCard(ttk.Frame):
    def __init__(self, master, app, game_key):
        super().__init__(master, padding=14, relief="ridge")
        self.app = app
        self.game_key = game_key
        self.cfg = GAMES[game_key]
        self.analysis_open = False
        self.show_n = 3
        self._build()

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text=self.cfg.name, font=("Segoe UI", 18, "bold")).pack(side="left")
        self.status = ttk.Label(header, text="Loading…")
        self.status.pack(side="right")

        # Use the previously empty horizontal space: archive/model status on the left,
        # today's/next official draw lifecycle on the right.
        summary = ttk.Frame(self)
        summary.pack(fill="x", pady=(10,8))
        left_summary = ttk.Frame(summary)
        left_summary.pack(side="left", fill="both", expand=True)
        self.latest = ttk.Label(left_summary, text="Latest draw: —", font=("Segoe UI", 11))
        self.latest.pack(anchor="w", pady=(0,2))
        self.model_line = ttk.Label(left_summary, text="Production: —   |   Challenger: —   |   Neural: —")
        self.model_line.pack(anchor="w")
        self.jackpot_line = ttk.Label(left_summary, text="Jackpot: —", font=("Segoe UI", 10, "bold"))
        self.jackpot_line.pack(anchor="w", pady=(3,0))

        self.current_draw_box = ttk.LabelFrame(summary, text=self.app.t("next_draw"), padding=(10,6))
        self.current_draw_box.pack(side="right", fill="both", padx=(14,0))
        # A StringVar-backed label is deliberately used instead of a disabled Text
        # widget.  On some Windows ttk themes the disabled Text foreground could
        # render white, leaving an apparently empty panel even though the draw data
        # was present.  This widget is read-only by design and renders consistently.
        self.current_draw_var = tk.StringVar(value="Next scheduled draw: —\nNext jackpot: —")
        self.current_draw_text = tk.Label(
            self.current_draw_box, textvariable=self.current_draw_var,
            height=16, width=94, wraplength=790, justify="left", anchor="nw",
            font=("Consolas", 9), bd=0, relief="flat", bg="white", fg="black",
        )
        self.current_draw_text.pack(fill="both", expand=True)

        self.top_picks_label = ttk.Label(self, text=self.app.t("top_picks"), font=("Segoe UI", 10, "bold"))
        self.top_picks_label.pack(anchor="w")
        self.picks = tk.Text(self, height=5, wrap="none", font=("Consolas", 10), bd=0)
        self.picks.pack(fill="x", pady=(2,6))
        self.picks.configure(state="disabled")

        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        self.more_btn = ttk.Button(buttons, text=self.app.t("show_top_10"), command=self.toggle_more)
        self.more_btn.pack(side="left")
        self.predict_btn = ttk.Button(buttons, text=self.app.t("generate"), command=lambda:self.app.generate_official_async(self.game_key))
        self.predict_btn.pack(side="left", padx=6)
        self.analysis_btn = ttk.Button(buttons, text="▼ " + self.app.t("analysis"), command=self.toggle_analysis)
        self.analysis_btn.pack(side="right")

        self.analysis = ttk.Frame(self, padding=(0,10,0,0))
        nav = ttk.Frame(self.analysis)
        nav.pack(fill="x", pady=(0,6))
        nav_items=[("main","main"),("coverage","coverage"),("budget","budget"),("jackpot","jackpot"),("bonus","bonus")]
        if self.game_key == "649": nav_items.append(("goldball","goldball"))
        nav_items += [("weights","weights"),("learning","learning"),("research","research"),("data","data")]
        self.nav_buttons = {}
        for text_key, key in nav_items:
            btn=ttk.Button(nav, text=self.app.t(text_key), command=lambda k=key:self.show_analysis(k))
            btn.pack(side="left", padx=(0,5))
            self.nav_buttons[key]=btn

        self.bonus_selector_frame = ttk.Frame(self.analysis)
        self.bonus_selector_label = ttk.Label(self.bonus_selector_frame, text=self.app.t("based_on_pick") + ":")
        self.bonus_selector_label.pack(side="left")
        self.bonus_pick_var = tk.StringVar(value="#1")
        self.bonus_pick_combo = ttk.Combobox(self.bonus_selector_frame, textvariable=self.bonus_pick_var,
                                             width=7, state="readonly", values=("#1",))
        self.bonus_pick_combo.pack(side="left", padx=(6,0))
        self.bonus_pick_combo.bind("<<ComboboxSelected>>", lambda _e:self.show_analysis("bonus"))

        self.budget_selector_frame = ttk.Frame(self.analysis)
        ttk.Label(self.budget_selector_frame, text="Budget / 预算:").pack(side="left")
        self.budget_var = tk.StringVar(value="Auto")
        self.budget_combo = ttk.Combobox(
            self.budget_selector_frame, textvariable=self.budget_var, width=14, state="normal",
            values=("Auto", "$10", "$20", "$30", "$50", "$100"))
        self.budget_combo.pack(side="left", padx=(6,0))
        self.budget_combo.bind("<<ComboboxSelected>>", lambda _e:self.show_analysis("budget"))
        self.budget_combo.bind("<Return>", lambda _e:self.show_analysis("budget"))
        ttk.Label(self.budget_selector_frame, text="  Custom: type e.g. 37 / 可输入自定义金额").pack(side="left")

        self.analysis_text = tk.Text(self.analysis, height=15, wrap="word", font=("Consolas",9))
        self.analysis_text.pack(fill="both", expand=True)
        self.analysis_text.configure(state="disabled")
        self.show_analysis("main")

    def toggle_analysis(self):
        self.analysis_open = not self.analysis_open
        if self.analysis_open:
            self.analysis.pack(fill="both", expand=True)
            self.analysis_btn.configure(text="▲ " + self.app.t("analysis"))
        else:
            self.analysis.pack_forget()
            self.analysis_btn.configure(text="▼ " + self.app.t("analysis"))

    def toggle_more(self):
        if self.show_n == 3:
            self.show_n = 10; label = self.app.t("show_top_20")
        elif self.show_n == 10:
            self.show_n = 20; label = self.app.t("show_top_3")
        else:
            self.show_n = 3; label = self.app.t("show_top_10")
        self.more_btn.configure(text=label)
        self.refresh()

    def set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0","end")
        widget.insert("1.0",text)
        widget.configure(state="disabled")

    @staticmethod
    def _million_text(value):
        if value is None:
            return "—"
        try:
            return f"${float(value):.1f}M"
        except (TypeError, ValueError):
            return "—"

    def _current_draw_text(self, snapshot, jackpot=None):
        if not snapshot:
            if self.app.language_mode == "zh":
                return "下一期开奖日期: —\n下一期头奖: —"
            if self.app.language_mode == "bilingual":
                return "Next draw / 下一期开奖日期: —\nNext jackpot / 下一期头奖: —"
            return "Next draw date: —\nNext jackpot: —"
        d = snapshot.get("draw_date", "—")
        status = snapshot.get("status", "NEXT_DRAW_WAITING")
        bilingual = self.app.language_mode == "bilingual"
        zh = self.app.language_mode == "zh"
        status_map = {
            "VERIFIED_RESULT": ("✓ VERIFIED OFFICIAL RESULT", "✓ 官方结果已验证"),
            "UNVERIFIED_RESULT": ("⚠ RESULT NOT VERIFIED", "⚠ 结果尚未验证"),
            "AWAITING_OFFICIAL_RESULT": ("WAITING FOR OFFICIAL RESULT", "等待官方开奖结果"),
            "PREDICTION_LOCKED": ("PREDICTION LOCKED · WAITING FOR DRAW", "预测已锁定 · 等待开奖"),
            "NEXT_DRAW_WAITING": ("NEXT DRAW · WAITING FOR PREDICTION/RESULT", "下期开奖 · 等待预测/结果"),
        }
        en_status, zh_status = status_map.get(status, (status, status))
        st = zh_status if zh else (en_status if not bilingual else f"{en_status} / {zh_status}")
        try:
            draw_day = date.fromisoformat(str(d)[:10]).strftime("%A")
        except (TypeError, ValueError):
            draw_day = ""
        if zh:
            date_line = f"开奖日期: {d}" + (f" ({draw_day})" if draw_day else "")
        elif bilingual:
            date_line = f"Draw date / 开奖日期: {d}" + (f" ({draw_day})" if draw_day else "")
        else:
            date_line = f"Draw date: {d}" + (f" ({draw_day})" if draw_day else "")
        lines = [date_line, st]

        # Put the upcoming prize where it is immediately visible.  The detailed
        # Jackpot analysis remains available in the hidden menu; this is the same
        # latest official/cached snapshot already used there, never an invented value.
        jackpot = jackpot or {}
        if self.game_key == "max":
            amount = self._million_text(jackpot.get("jackpot_million"))
            prize_line = (f"下一期头奖: {amount}" if zh else
                          (f"Next jackpot / 下一期头奖: {amount}" if bilingual else
                           f"Next jackpot: {amount}"))
        else:
            classic = self._million_text(jackpot.get("classic_jackpot_million", 5.0))
            gold = self._million_text(jackpot.get("gold_ball_jackpot_million"))
            prize_line = (f"下一期奖金: Classic {classic} | Gold Ball {gold}" if zh else
                          (f"Next prizes / 下一期奖金: Classic {classic} | Gold Ball {gold}" if bilingual else
                           f"Next prizes: Classic {classic} | Gold Ball {gold}"))
        if str(jackpot.get("status") or "").upper() in {"STALE", "FAILED"}:
            prize_line += "  [缓存/待更新]" if zh else ("  [cached / 待更新]" if bilingual else "  [cached; refresh pending]")
        lines.append(prize_line)
        result = snapshot.get("result")
        if result:
            win = fmt_numbers(result.get("numbers") or [])
            if zh:
                lines.append(f"开奖号码: {win}   特别号 {result.get('bonus','—')}")
            elif bilingual:
                lines.append(f"Winning / 开奖: {win}   Bonus / 特别号 {result.get('bonus','—')}")
            else:
                lines.append(f"Winning: {win}   Bonus {result.get('bonus','—')}")

            leaders = snapshot.get("match_leaders") or []
            if leaders:
                leader_bits = [f"#{r.get('rank')} {r.get('main_hits')}/{self.cfg.pick}" for r in leaders[:4]]
                prefix = "命中排行" if zh else ("Match leaders / 命中排行" if bilingual else "Match leaders")
                lines.append(prefix + ": " + "   ".join(leader_bits))

                champs = snapshot.get("champions") or []
                if champs:
                    first = champs[0]
                    nums = fmt_numbers(first.get("numbers") or [])
                    matched = fmt_numbers(first.get("matched_numbers") or []) or "—"
                    pool = ",".join(f"#{int(x)}" for x in (snapshot.get("champion_ranks") or []))
                    first_rank = int(first.get("rank") or 0)
                    if len(champs) > 1:
                        if zh:
                            lines.append(f"并列最高命中排名: {pool} | 示例 #{first_rank}: {nums}   命中 {matched}")
                        elif bilingual:
                            lines.append(f"Tied best-hit ranks / 并列最高命中: {pool} | Example #{first_rank}: {nums}   Hit {matched}")
                        else:
                            lines.append(f"Tied best-hit ranks: {pool} | Example #{first_rank}: {nums}   Hit {matched}")
                    else:
                        label = "最高命中组" if zh else ("Champion / 最高命中组" if bilingual else "Champion")
                        lines.append(f"{label} #{first_rank}: {nums}   Hit {matched}")

                n = int(snapshot.get("top_n") or 0)
                unique = snapshot.get("portfolio_unique_numbers")
                pool_size = snapshot.get("number_pool_size") or self.cfg.max_number
                slots = snapshot.get("ticket_slots")
                cov = snapshot.get("top_n_coverage")
                if zh:
                    lines.append(f"组合池: {n}组 | {slots}个位置 | {unique}/{pool_size}个不重复数字 | 组合池中奖号码覆盖 {cov}/{self.cfg.pick}")
                elif bilingual:
                    lines.append(f"Portfolio / 组合池: {n} tickets | {slots} slots | {unique}/{pool_size} unique | portfolio winning-number coverage {cov}/{self.cfg.pick}")
                else:
                    lines.append(f"Portfolio: {n} tickets | {slots} slots | {unique}/{pool_size} unique | portfolio winning-number coverage {cov}/{self.cfg.pick}")

                rc = (snapshot.get("rank_concentration") or {}).get("by_k") or {}
                if rc:
                    keys = [k for k in ("3","5","10","20") if k in rc]
                    cwc = "  ".join(f"@{k} {rc[k].get('cumulative_winner_coverage')}/{self.cfg.pick}" for k in keys)
                    bh = "  ".join(f"@{k} {rc[k].get('best_ticket_hit')}/{self.cfg.pick}" for k in keys)
                    lines.append(("累计覆盖 CWC: " if zh else "CWC: ") + cwc)
                    lines.append(("单组最佳 BestHit: " if zh else "BestHit: ") + bh)

                cand = snapshot.get("candidate_number_ranking") or {}
                if cand.get("available"):
                    byk = cand.get("by_k") or {}
                    bits = [f"@{k} {byk[k].get('winner_coverage')}/{self.cfg.pick}" for k in ("10","15","20") if k in byk]
                    if bits:
                        label = "候选数字排名覆盖" if zh else ("Candidate-number rank / 候选数字排名" if bilingual else "Candidate-number rank")
                        lines.append(label + ": " + "  ".join(bits))
                else:
                    lines.append("候选数字排名: 旧冻结数据未保存" if zh else "Candidate-number rank: unavailable for this legacy freeze")

                gap = snapshot.get("combination_gap")
                wce = snapshot.get("winner_concentration_efficiency")
                bottleneck = snapshot.get("bottleneck") or "—"
                if zh:
                    lines.append(f"组合集中: gap {gap} | WCE {100*float(wce or 0):.1f}% | {bottleneck}")
                elif bilingual:
                    lines.append(f"Concentration / 集中: gap {gap} | WCE {100*float(wce or 0):.1f}% | {bottleneck}")
                else:
                    lines.append(f"Concentration: gap {gap} | WCE {100*float(wce or 0):.1f}% | {bottleneck}")

                cr=snapshot.get("champion_best_original_rank")
                pct=snapshot.get("champion_score_percentile")
                rho=float(snapshot.get("score_hit_spearman") or 0.0)
                rdiag=snapshot.get("ranking_diagnosis") or "—"
                if cr is not None:
                    corr_diag=classify_rank_association(rho)
                    if zh:
                        lines.append(f"最高命中组排名: {rdiag} (#{cr}/{n}) | 分数百分位 {pct}%")
                        lines.append(f"整体排序相关: {corr_diag} | Spearman {rho:+.3f}")
                    elif bilingual:
                        lines.append(f"Champion placement / 最高命中组排名: {rdiag} (#{cr}/{n}) | Score pct {pct}%")
                        lines.append(f"Overall rank correlation / 整体排序相关: {corr_diag} | Spearman {rho:+.3f}")
                    else:
                        lines.append(f"Champion placement: {rdiag} (#{cr}/{n}) | Score pct {pct}%")
                        lines.append(f"Overall rank correlation: {corr_diag} | Spearman {rho:+.3f}")

                if snapshot.get("snapshot_consistency") != "OK":
                    lines.append(f"⚠ Freeze consistency: {snapshot.get('snapshot_consistency')}")
                saved = snapshot.get("champion_learning_saved")
                lines.append(("Champion Shadow: 已保存 ✓" if saved and zh else
                              "Champion Shadow: 等待保存" if zh else
                              f"Champion Shadow: {'saved ✓' if saved else 'pending'} | Production impact 0%"))
            elif not snapshot.get("prediction_locked"):
                lines.append("No frozen official prediction for this draw. / 本期没有冻结的正式预测。" if bilingual else
                             ("本期没有冻结的正式预测。" if zh else "No frozen official prediction for this draw."))
        else:
            if snapshot.get("prediction_locked"):
                lock = snapshot.get("freeze_created") or "—"
                lines.append(f"正式预测已锁定: {lock}" if zh else
                             (f"Official prediction locked / 正式预测已锁定: {lock}" if bilingual else f"Official prediction locked: {lock}"))
            else:
                lines.append("Winning numbers: —   Bonus: —" if not zh else "开奖号码: —   特别号: —")
        return "\n".join(lines[:18])

    def refresh(self):
        state = self.app.game_state.get(self.game_key, {})
        latest = state.get("latest")
        has_cov=any((r.get("coverage_engine") for r in (state.get("preds") or [])))
        self.top_picks_label.configure(text=self.app.t("coverage_optimized_picks") if has_cov else self.app.t("top_picks"))
        self.bonus_selector_label.configure(text=self.app.t("based_on_pick") + ":")
        draw_snapshot = state.get("current_draw") or {}
        self.current_draw_box.configure(
            text=self.app.t("current_draw") if draw_snapshot.get("scheduled_today") else self.app.t("next_draw")
        )
        self.current_draw_var.set(self._current_draw_text(draw_snapshot, state.get("jackpot")))
        self.more_btn.configure(text=self.app.t("show_top_20") if self.show_n==3 else (self.app.t("show_top_3") if self.show_n==10 else self.app.t("show_top_10")))
        self.analysis_btn.configure(text=("▲ " if self.analysis_open else "▼ ") + self.app.t("analysis"))
        for key, btn in getattr(self, "nav_buttons", {}).items():
            btn.configure(text=self.app.t(key))
        if latest:
            ver = ("✓ verified / 已验证" if self.app.language_mode == "bilingual" else
                   ("✓ verified" if latest.get("verified") and self.app.language_mode == "en" else
                    ("✓ 已验证" if latest.get("verified") else "unverified / 未验证")))
            if not latest.get("verified") and self.app.language_mode == "en":
                ver = "unverified source"
            self.latest.configure(text=f"Latest draw / 最新开奖 {latest['draw_date']}:  {fmt_numbers(latest['numbers'])}    Bonus / 特别号 {latest.get('bonus','—')}   [{ver}]" if self.app.language_mode == "bilingual" else
                                  (f"Latest draw {latest['draw_date']}:  {fmt_numbers(latest['numbers'])}    Bonus {latest.get('bonus','—')}   [{ver}]" if self.app.language_mode == "en" else
                                   f"最新开奖 {latest['draw_date']}:  {fmt_numbers(latest['numbers'])}    特别号 {latest.get('bonus','—')}   [{ver}]"))
        self.status.configure(text=state.get("status","Ready"))
        if self.app.language_mode == "zh":
            self.model_line.configure(text=f"正式模型: {state.get('pver','—')}   |   挑战模型: {state.get('cver','—')}   |   随机对照: {state.get('random_status','—')}   |   神经模型: {state.get('nn_status','—')}")
        elif self.app.language_mode == "bilingual":
            self.model_line.configure(text=f"Production/正式: {state.get('pver','—')}   |   Challenger/挑战: {state.get('cver','—')}   |   Random/随机: {state.get('random_status','—')}   |   Neural/神经: {state.get('nn_status','—')}")
        else:
            self.model_line.configure(text=f"Production: {state.get('pver','—')}   |   Challenger: {state.get('cver','—')}   |   Random: {state.get('random_status','—')}   |   Neural: {state.get('nn_status','—')}")
        js=state.get("jackpot") or {}
        je=state.get("jackpot_economics") or {}
        cp=(je.get("crowd_pressure_proxy") or {}).get("level","UNKNOWN")
        if self.game_key=="max":
            jv=js.get("jackpot_million")
            self.jackpot_line.configure(text=f"Latest official jackpot / 最新官方奖池: ${jv if jv is not None else '—'}M   |   Crowd proxy {cp}")
        else:
            jv=js.get("gold_ball_jackpot_million")
            balls=js.get("gold_balls_remaining")
            self.jackpot_line.configure(text=f"Gold Ball / 金球奖池: ${jv if jv is not None else '—'}M   |   Balls {balls if balls is not None else '—'}   |   Crowd proxy {cp}")

        target = state.get("target")
        frozen = bool(state.get("prediction_frozen"))
        can_generate = bool(state.get("can_generate", False))
        if frozen:
            created = format_bc_timestamp(state.get("prediction_created", ""))
            self.predict_btn.configure(text=f"✓ {self.app.t('prediction_frozen')} · {target or '—'}", state="disabled")
            self.status.configure(text=self.app.t("official_locked") + (f" · {created}" if created else ""))
        elif can_generate:
            self.predict_btn.configure(text=f"{self.app.t('generate')} · {target or 'Next Draw'}", state="normal")
        else:
            self.predict_btn.configure(text=self.app.t("update_before"), state="disabled")

        rows = state.get("preds",[])[:self.show_n]
        payload = state.get("bonus_payload") or {}
        consistency = state.get("main_bonus_consistency") or {}
        error_ranks = {int(e.get("main_rank", -1)) for e in consistency.get("errors") or []}
        lines=[]
        for r in rows:
            rank=int(r.get('rank', len(lines)+1))
            bonus=bonus_top_for_pick(payload, rank, state.get("preds",[]))
            btxt="ERR" if rank in error_ranks else (f"{int(bonus):02d}" if bonus is not None else "—")
            pv = r.get("portfolio_value")
            ptxt = f" | {self.app.t('portfolio_value')} {float(pv):>5.2f}" if pv is not None else ""
            lines.append(
                f"#{rank:>2}  {fmt_numbers(r['numbers'])} | {self.app.t('combination_score')} {float(r['score']):>5.2f}{ptxt} | "
                f"{self.app.t('bonus')} {btxt} | {self.app.t('crowd')} {r.get('crowd_risk','—')}"
            )
        if not lines:
            lines=["No official prediction yet. Update data, then generate once for the next draw. / 尚无正式预测，请先更新数据。" if self.app.language_mode == "bilingual" else
                   ("No official prediction yet. Update data, then generate once for the next draw." if self.app.language_mode == "en" else
                    "尚无正式预测，请先更新数据后生成下一期预测。")]
        self.picks.configure(height=max(4,min(12,len(lines)+1)))
        self.set_text(self.picks,"\n".join(lines))

        pick_count=max(1, len(state.get("preds",[]) or []))
        values=tuple(f"#{i}" for i in range(1,pick_count+1))
        self.bonus_pick_combo.configure(values=values)
        if self.bonus_pick_var.get() not in values:
            self.bonus_pick_var.set("#1")
        if self.analysis_open:
            self.show_analysis(state.get("analysis_tab","main"))

    def show_analysis(self, key):
        state = self.app.game_state.get(self.game_key,{})
        state["analysis_tab"] = key
        self.app.game_state[self.game_key]=state
        txt=""
        self.bonus_selector_frame.pack_forget()
        self.budget_selector_frame.pack_forget()
        if key == "bonus":
            self.bonus_selector_frame.pack(fill="x", pady=(0,6), before=self.analysis_text)
        if key == "budget":
            self.budget_selector_frame.pack(fill="x", pady=(0,6), before=self.analysis_text)
        if key=="main":
            reg=state.get("region",{}) or {}
            if not reg:
                sd=exact_sum_distribution(self.cfg.max_number,self.cfg.pick)
                spd=exact_span_distribution(self.cfg.max_number,self.cfg.pick)
                reg={"expected_sum":self.cfg.pick*(self.cfg.max_number+1)/2,"sum_50":central_interval(sd,.50),"sum_75":central_interval(sd,.75),"sum_90":central_interval(sd,.90),"span_75":central_interval(spd,.75)}
            txt += "REGION ENGINE (exact combinatorial marginals)\n"
            txt += f"Expected sum: {reg.get('expected_sum','—')}\n"
            txt += f"50% sum region: {reg.get('sum_50','—')}\n75% sum region: {reg.get('sum_75','—')}\n90% sum region: {reg.get('sum_90','—')}\n"
            txt += f"75% span region: {reg.get('span_75','—')}\n\n"
            if state.get("preds"):
                r=state["preds"][0]
                txt += "TOP PICK FACTOR SCORES\n"
                for k,v in r["components"].items():
                    label = "monte_carlo (diagnostic, 0% weight)" if k == "monte_carlo" else k
                    txt += f"{label:34s} {v:6.2f}\n"
                if r.get("nn_shadow") is not None: txt += f"NN shadow        {r['nn_shadow']:6.2f}  (0% production weight)\n"
            txt += "\nCombination Score is a Main-combination ranking score, NOT a jackpot probability. / 组合评分仅用于主号组合排序，不代表头奖概率。"
        elif key=="coverage":
            ps=state.get("coverage_summary") or {}
            txt="COMBINATION COVERAGE OPTIMIZER / 组合覆盖优化器\n\n"
            if not ps:
                txt += "No frozen Coverage portfolio yet. Legacy frozen predictions remain unchanged. / 尚无新版覆盖优化冻结组合；旧版冻结预测保持不变。\n"
            else:
                txt += f"Engine: {ps.get('coverage_engine','—')}   Mode: {str(ps.get('mode','—')).upper()}\n"
                txt += f"Model-directed lines: {ps.get('lines','—')}   Terminal selections per purchase: {ps.get('lines_per_play','—')}\n"
                txt += f"Purchases required to direct every displayed line: {ps.get('model_directed_purchases','—')}   cost=${ps.get('model_directed_cost_if_all','—')}\n"
                if int(ps.get('companion_quick_pick_lines_if_all',0) or 0) > 0:
                    txt += f"Companion terminal Quick Picks (not credited to the model): {ps.get('companion_quick_pick_lines_if_all')}   total physical lines={ps.get('total_physical_lines_if_all','—')}\n"
                txt += f"Unique numbers: {ps.get('unique_numbers','—')}/{ps.get('number_pool_size','—')}   Pool coverage: {ps.get('number_pool_coverage_pct','—')}%\n"
                txt += f"Unique pairs: {ps.get('unique_pairs','—')}/{ps.get('pair_slots','—')} slots   Reuse: {ps.get('pair_reuse','—')}   Efficiency: {ps.get('pair_efficiency_pct','—')}%\n"
                txt += f"Unique triples: {ps.get('unique_triples','—')}/{ps.get('triple_slots','—')} slots   Reuse: {ps.get('triple_reuse','—')}   Efficiency: {ps.get('triple_efficiency_pct','—')}%\n"
                txt += f"Avg overlap: {ps.get('avg_pair_overlap','—')}   Max overlap: {ps.get('max_pair_overlap','—')}\n"
                txt += f"Structure diversity: {ps.get('structure_diversity_pct','—')}%\n"
                txt += f"Avg Combination Score: {ps.get('avg_combination_score','—')}\n"
                txt += f"Coverage Efficiency: {ps.get('coverage_efficiency','—')}   Portfolio Score: {ps.get('portfolio_score','—')}\n\n"
                txt += "Official mode is BALANCED: Combination Score remains the dominant input; Pair/Triple/Number coverage only chooses portfolio membership.\n"
                txt += "Coverage does NOT change the official probability of an individual legal lottery combination. / 覆盖优化不会改变单一合法号码组合的官方中奖概率。\n\n"
                cprof=state.get("candidate_number_profile") or []
                if cprof:
                    nums=[int(x.get("number")) for x in cprof if isinstance(x,dict) and x.get("number") is not None]
                    txt += "PRE-DRAW CANDIDATE-NUMBER SUPPORT RANK / 开奖前候选数字支持排名\n"
                    txt += "  Top 10: " + fmt_numbers(nums[:10]) + "\n"
                    txt += "  Top 20: " + fmt_numbers(nums[:20]) + "\n"
                    txt += "This is a support ranking derived from the scored candidate pool; it is not a number-level jackpot probability.\n\n"
                else:
                    txt += "Pre-draw candidate-number rank is unavailable for this legacy freeze. New V1.5.5 freezes retain it for independent post-draw evaluation.\n\n"
                matrix=state.get("coverage_matrix") or []
                if matrix:
                    shown=min(len(matrix),12)
                    txt += f"OVERLAP MATRIX — first {shown} displayed picks (shared main numbers)\n    " + " ".join(f"{i+1:>2}" for i in range(shown)) + "\n"
                    for i,row in enumerate(matrix[:shown]):
                        txt += f"{i+1:>2}: " + " ".join(" -" if i==j else f"{int(v):>2}" for j,v in enumerate(row[:shown])) + "\n"
                    txt += "Soft guide: 6/49 <=2 shared is normal; LOTTO MAX <=3 shared is normal. Higher overlap is penalized, not absolutely banned.\n"
            txt += "\nFocused Compression, Pure Coverage, and Concentrated exist as Research/benchmark modes only; they cannot auto-replace official Production.\n"
        elif key=="budget":
            dec=state.get("portfolio_decision") or {}
            frontier=(dec.get("production_frontier") or {})
            learning=state.get("portfolio_learning_status") or {}
            validation=state.get("portfolio_validation") or {}
            txt="ADAPTIVE BUDGET & PORTFOLIO AI / 自适应预算与组合AI\n\n"
            if not frontier:
                txt += "No V1.5 frozen portfolio frontier yet. Generate/freeze the next official Top-20 first. / 尚无V1.5冻结预算前沿。\n"
            else:
                raw=str(self.budget_var.get() or "Auto").strip()
                frozen_budget_learning=dec.get("budget_learning_at_freeze") or state.get("budget_learning") or {}
                if raw.lower().startswith("auto"):
                    n_budget=int(frozen_budget_learning.get("n",0) or 0)
                    empirical_k=frozen_budget_learning.get("research_best_lines")
                    supported=bool(frozen_budget_learning.get("selection_supported"))
                    research_choice=None
                    if n_budget >= PORTFOLIO_PROVISIONAL_N and empirical_k is not None and str(int(empirical_k)) in (frontier.get("frontier") or {}):
                        research_choice=dict(frontier["frontier"][str(int(empirical_k))])
                        research_choice["method"]="draw-level empirical research candidate frozen from prior outcomes"
                    else:
                        research_choice=dict(frontier.get("auto") or {})
                    if supported and empirical_k is not None and str(int(empirical_k)) in (frontier.get("frontier") or {}):
                        choice=dict(frontier["frontier"][str(int(empirical_k))])
                        choice["method"]="evidence-gated learned budget choice"
                        mode="AUTO / EVIDENCE-SUPPORTED"
                    else:
                        choice={"lines":0,"cost":0.0,"selected_ranks":[],"features":{},"policy_value":0.0,"status":"NO_BET_EVIDENCE_GATE"}
                        mode="AUTO / NO BET (research candidate shown below)"
                    budget=None
                else:
                    try:
                        budget=float(raw.replace("$","").replace(",",""))
                    except Exception:
                        budget=20.0
                    opt=PortfolioOptimizer(self.game_key)
                    choice=opt.for_budget(frontier,budget,allow_unspent=True)
                    full_budget_choice=opt.for_budget(frontier,budget,allow_unspent=False)
                    mode=f"MAX BUDGET ${budget:.2f}"
                budget_evidence_n=int(frozen_budget_learning.get("n",0) or 0)
                budget_phase=frozen_budget_learning.get("phase") or portfolio_phase(budget_evidence_n).get("phase")
                shadow_n=int(learning.get("n",0) or 0)
                grade=frozen_budget_learning.get("selection_evidence_grade","D")
                txt += (f"Mode: {mode}   Budget Evidence Phase: {budget_phase}   "
                        f"Paired budget samples: {budget_evidence_n}   Selection Evidence Grade: {grade}\n")
                if shadow_n != budget_evidence_n:
                    txt += f"Shadow-policy learning samples: {shadow_n} (tracked separately from budget-selection evidence).\n"
                txt += f"Play cost: ${float(self.cfg.play_cost):.2f} per model-directed selection/purchase\n"
                if mode.startswith("AUTO"):
                    n_freeze=int(frozen_budget_learning.get("n",0) or 0)
                    if n_freeze < PORTFOLIO_PROVISIONAL_N:
                        txt += "Action: RESEARCH ONLY — insufficient forward samples for an empirical budget choice.\n"
                        txt += "The line count below is the pre-draw structural sweet spot, not a claimed profitable bet.\n"
                    elif frozen_budget_learning.get("selection_supported"):
                        txt += "Action: EVIDENCE-SUPPORTED SUBSET SELECTION vs same-budget random within the frozen Top-20. This does NOT imply positive expected profit.\n"
                    else:
                        txt += "Action: NO SUPPORTED EDGE YET. The learned line count is shown as a research candidate; strict evidence-gated auto-spend remains $0.\n"
                if raw.lower().startswith("auto") and research_choice:
                    txt += (f"Research candidate only: {int(research_choice.get('lines',0))} lines / ${float(research_choice.get('cost',0)):.2f}   "
                            f"method={research_choice.get('method','structural')}\n")
                if frozen_budget_learning.get("research_best_lines") is not None:
                    bk=str(int(frozen_budget_learning.get("research_best_lines")))
                    bm=(frozen_budget_learning.get("by_lines") or {}).get(bk) or {}
                    txt += (f"Frozen learned candidate: {bk} lines / ${float(frozen_budget_learning.get('research_best_budget') or 0):.2f}   "
                            f"objective={frozen_budget_learning.get('budget_selection_objective','—')}   model-line ROI floor={frozen_budget_learning.get('research_best_roi_floor','—')}   "
                            f"same-budget best-hit edge={bm.get('mean_best_hit_edge_vs_random','—')}   q(FDR)={bm.get('best_hit_edge_fdr_q','—')}\n")
                    txt += f"Evidence note: {frozen_budget_learning.get('evidence_note','—')}\n"
                if budget is not None:
                    txt += f"Maximum budget (hard ceiling): ${budget:.2f}\n"
                    sweet_label = ("Structural sweet-spot candidate (NOT ROI-VALIDATED)"
                                   if budget_evidence_n < PORTFOLIO_PROVISIONAL_N else "Efficiency sweet spot")
                    txt += (f"{sweet_label}: {choice.get('lines',0)} model-directed purchases | "
                            f"spend ${float(choice.get('cost',0)):.2f} | deliberately unspent ${float(choice.get('unused',0)):.2f} | "
                            f"frontier MV/$ {float(choice.get('marginal_value_per_dollar',0)):.5f}\n")
                    txt += (f"Full-capacity plan (NOT a recommendation): {full_budget_choice.get('lines',0)} purchases | "
                            f"spend ${float(full_budget_choice.get('cost',0)):.2f} | unusable remainder ${float(full_budget_choice.get('unused',0)):.2f}\n")
                    if float(choice.get('unused',0) or 0) >= float(self.cfg.play_cost):
                        txt += "Efficiency-plan note: the remaining budget is intentionally left unspent after the structural knee; it is not a claim that later tickets have negative expected value.\n"
                    if (int(full_budget_choice.get('lines',0) or 0) >= int(frontier.get('lines',0) or 0)
                            and float(full_budget_choice.get('unused',0) or 0) > 0):
                        txt += "Full-capacity remainder: all frozen Top-20 model combinations are already deployed; the optimizer will not invent extra combinations just to spend the budget.\n"
                    elif 0 < float(full_budget_choice.get('unused',0) or 0) < float(self.cfg.play_cost):
                        txt += "Full-capacity remainder: the next legal model-directed purchase would exceed the budget cap.\n"
                    txt += "Plan-membership note: each exact-k subset is optimized independently; the full-capacity plan is not necessarily the efficiency plan plus extra ranks.\n"
                else:
                    txt += f"Selected: {choice.get('lines',0)} / {frontier.get('lines',0)} model-directed plays   Cost: ${float(choice.get('cost',0)):.2f}\n"
                rank_label = "Efficiency-plan ranks" if budget is not None else "Ranks"
                txt += rank_label + ": " + (" ".join(f"#{int(x)}" for x in (choice.get("selected_ranks") or [])) or "0 / NO BET") + "\n"
                byrank={int(r.get('rank',i+1)):r for i,r in enumerate(state.get('preds') or [])}
                role_by_rank={int(x.get('rank')):x for x in (choice.get('line_roles') or []) if isinstance(x,dict) and x.get('rank') is not None}
                for rr in (choice.get("selected_ranks") or []):
                    row=byrank.get(int(rr))
                    if row:
                        role=(role_by_rank.get(int(rr)) or {}).get('role','BALANCED')
                        txt += f"  #{int(rr):>2}  {fmt_numbers(row.get('numbers') or [])}   Score {float(row.get('score',0)):.2f}   Role {role}\n"
                if budget is not None:
                    full_roles={int(x.get('rank')):x for x in (full_budget_choice.get('line_roles') or []) if isinstance(x,dict) and x.get('rank') is not None}
                    txt += "\nFull-capacity plan ranks: " + (" ".join(f"#{int(x)}" for x in (full_budget_choice.get("selected_ranks") or [])) or "0") + "\n"
                    for rr in (full_budget_choice.get("selected_ranks") or []):
                        row=byrank.get(int(rr))
                        if row:
                            role=(full_roles.get(int(rr)) or {}).get('role','BALANCED')
                            txt += f"  #{int(rr):>2}  {fmt_numbers(row.get('numbers') or [])}   Score {float(row.get('score',0)):.2f}   Role {role}\n"
                if self.game_key == 'max' and int(choice.get('lines',0) or 0) > 0:
                    plays=int(choice.get('lines',0) or 0)
                    txt += f"LOTTO MAX efficiency package: {plays} chosen combinations + {plays*3} terminal Quick Picks = {plays*4} physical selections.\n"
                    if budget is not None:
                        fullplays=int(full_budget_choice.get('lines',0) or 0)
                        txt += f"LOTTO MAX full-capacity package: {fullplays} chosen combinations + {fullplays*3} terminal Quick Picks = {fullplays*4} physical selections.\n"
                f=choice.get("features") or {}
                if f:
                    div_text=(f"{float(f.get('diversity',0)):.3f}" if f.get('diversity_applicable',True) else "N/A (single line)")
                    txt += (f"\nStructural metrics: quality={float(f.get('quality',0)):.3f}  number coverage={float(f.get('number_coverage',0)):.3f}  "
                            f"diversity={div_text}  concentration={float(f.get('concentration',0)):.3f}  "
                            f"rank retention={float(f.get('rank_retention',0)):.3f} [guardrail, not a cross-budget bonus]\n")
                txt += "\nEXACT DEPLOYMENT CURVE / 精确投入曲线\n"
                txt += "  (Each row is independently optimized at exactly that spend; MV/$ is the frontier value difference between spend levels, NOT a literal add-one-ticket path.)\n"
                for kk in sorted((frontier.get('frontier') or {}), key=lambda x:int(x)):
                    c=(frontier.get('frontier') or {}).get(kk) or {}
                    txt += (f"  {int(c.get('lines',0)):>2} lines | spend ${float(c.get('cost',0)):>6.2f} | "
                            f"deploy {float(c.get('deployment_utility_envelope',0)):.4f} | "
                            f"MV/$ {float(c.get('marginal_value_per_dollar',0)):.5f} | fixed-k value {float(c.get('policy_value',0)):.4f}\n")
                txt += "\nSTANDARD BUDGET CAPS / 标准预算上限（最大部署）\n"
                for b in PORTFOLIO_DEFAULT_BUDGETS:
                    c=PortfolioOptimizer(self.game_key).for_budget(frontier,b,allow_unspent=False)
                    txt += f"  ${b:>5.0f}: {int(c.get('lines',0)):>2} lines | spend ${float(c.get('cost',0)):>5.2f} | unused ${float(c.get('unused',0)):>5.2f}\n"
                txt += (f"\nBudget evidence confidence: {frozen_budget_learning.get('confidence','VERY LOW')}   "
                        f"Shadow-policy confidence: {learning.get('confidence','VERY LOW')}   Shadow production impact: {learning.get('production_impact',0)}%\n"
                        f"Validation draws: {validation.get('n',0)}   Prod-vs-random best-hit edge: {validation.get('production_vs_random_best_hit_edge','—')}\n")
                txt += "Effective sample size = number of draws, NOT the number of tested subsets. / 有效样本按开奖期数计算，不把百万子集当独立样本。\n"
                if self.game_key=="max":
                    txt += "\nLOTTO MAX accounting note: each $6 purchase contains one model-directed selection plus three terminal Quick Picks. Model-line ROI is NOT exact package ROI. Exact investment ROI requires the terminal/receipt payout for the whole purchase; companion lines are never falsely credited to the model.\n"
                else:
                    txt += "\nLOTTO 6/49 accounting note: each $3 play contains one model-directed Classic line plus a system-assigned Gold Ball selection. Model-line ROI is NOT exact package ROI. Exact investment ROI requires the Gold Ball/whole-ticket payout; Gold Ball outcomes remain separate from number-model skill.\n"
                txt += "\nNo Martingale / loss-chasing: the optimizer never raises budget because prior draws lost. User budget is always a hard ceiling.\n"
        elif key=="jackpot":
            snap=state.get("jackpot") or {}
            econ=state.get("jackpot_economics") or {}
            txt="LATEST OFFICIAL JACKPOT / 最新官方奖池\n\n"
            if not snap:
                txt += "Jackpot snapshot unavailable. Use Update Data Now; cached values are never presented as live without their timestamp.\n"
            else:
                txt += f"Source: {snap.get('source','—')}\nObserved: {snap.get('observed_at','—')}\nStatus: {snap.get('status','CURRENT')}\n"
                if self.game_key=="max":
                    txt += f"LOTTO MAX jackpot: ${snap.get('jackpot_million','—')}M / ${snap.get('jackpot_cap_million',90)}M cap\n"
                    txt += f"Additional $100K draws: {snap.get('maxplus_100k_count','—')}   MAXMILLIONS: {snap.get('maxmillions_count','—')}\n"
                else:
                    txt += f"Classic Jackpot: ${snap.get('classic_jackpot_million',5)}M\n"
                    txt += f"Gold Ball Jackpot: ${snap.get('gold_ball_jackpot_million','—')}M   Balls remaining: {snap.get('gold_balls_remaining','—')}\n"
                    p=econ.get('conditional_gold_ball_probability')
                    if p is not None:
                        txt += f"Conditional Gold-Ball probability after a Gold Ball selection is chosen: {100*float(p):.3f}%\n"
                    cvs=econ.get('gold_ball_conditional_value_score')
                    if cvs is not None:
                        txt += f"Gold-Ball conditional prize-attractiveness score: {float(cvs):.1f}/100 (separate from crowd pressure)\n"
                    txt += "Per-play Gold Ball odds also depend on issued selections; the app will not invent sales counts.\n"
                cp=econ.get('crowd_pressure_proxy') or {}
                txt += f"Crowd-pressure proxy: {cp.get('level','UNKNOWN')} ({cp.get('score','—')})\n"
                txt += "Proxy means jackpot-state pressure, not measured ticket sales. Actual sales will replace this when a trustworthy source is available.\n"
                hist=state.get('jackpot_history') or []
                if hist:
                    txt += "\nRECENT JACKPOT SNAPSHOTS\n"
                    for h in hist[-10:]:
                        hs=h.get('snapshot') or {}
                        val=hs.get('jackpot_million') if self.game_key=='max' else hs.get('gold_ball_jackpot_million')
                        txt += f"  {h.get('observed_at','—')}  ${val if val is not None else '—'}M\n"
                txt += "\nJackpot state is frozen into each V1.5 portfolio decision as context for later ROI/crowd learning; it never changes the already-frozen Top-20 numbers.\n"
        elif key=="bonus":
            try:
                selected_rank=max(1,int(str(self.bonus_pick_var.get()).replace("#","")))
            except Exception:
                selected_rank=1
            payload=state.get("bonus_payload") or {}
            entry=None
            for item in (payload.get("by_pick") or []):
                if int(item.get("main_rank",-1))==selected_rank:
                    entry=item; break
            txt="BONUS SUBMODEL / 特别号子模型\n"
            txt += f"{self.app.t('based_on_pick')} #{selected_rank}\n"
            pred_main=[]
            for p in state.get("preds",[]) or []:
                if int(p.get("rank",-1)) == selected_rank:
                    pred_main=[int(n) for n in p.get("numbers",[])]; break
            main_nums=(entry or {}).get("main_numbers") or pred_main
            if main_nums:
                txt += f"{self.app.t('main_combo')}: {fmt_numbers(main_nums)}\n"
            txt += self.app.t("bonus_independent") + "\n\n"
            ranking=(entry or {}).get("ranking") or []
            for i,item in enumerate(ranking,1):
                txt += f"#{i:>2}  {int(item[0]):02d}   {self.app.t('bonus_conditional_score')} {float(item[1]):.2f}\n"
            if not ranking:
                if (state.get("bonus_payload") or {}).get("legacy"):
                    txt += self.app.t("bonus_missing_legacy") + "\n"
                else:
                    txt += self.app.t("bonus_missing") + "\n"
            txt += "\n" + self.app.t("not_comparable") + "\n"
            txt += self.app.t("bonus_immutable") + "\n"
            mode=state.get("bonus_binding_mode","—")
            mode_label={
                "LEGACY FROZEN · PICK #1 ONLY": self.app.t("legacy_pick1"),
                "V1.1 FROZEN PER-MAIN": self.app.t("v11_per_main"),
                "PARTIAL FROZEN BINDING": self.app.t("partial_frozen"),
                "FROZEN CONSISTENCY ERROR": self.app.t("frozen_error"),
            }.get(mode, mode)
            txt += f"{self.app.t('binding_mode')}: {mode_label}\n"
            consistency=state.get("main_bonus_consistency") or {}
            txt += (f"Main-Bonus consistency / 主号-特别号一致性: {consistency.get('status','—')}  |  "
                    f"bound {consistency.get('bound_main_picks',0)}/{consistency.get('total_main_picks',0)}  |  errors {len(consistency.get('errors') or [])}"
                    f" | warnings {len(consistency.get('warnings') or [])}\n")
            txt += "\nBonus Production weights / 特别号正式权重:\n"
            for k,v in state.get("bpweights",{}).items(): txt += f"  {k:18s} {100*v:6.2f}%\n"
            txt += "Bonus Challenger weights / 特别号挑战权重:\n"
            for k,v in state.get("bcweights",{}).items(): txt += f"  {k:18s} {100*v:6.2f}%\n"
            txt += "\nBonus Conditional Score never participates in Main Combination ranking. / 特别号条件评分不会参与主号组合排序。"
        elif key=="goldball":
            gb=state.get("jackpot") or self.app.db.get_state("649_gold_ball",{}) or {}
            balls=gb.get("gold_balls_remaining", gb.get("balls_remaining"))
            jackpot=gb.get("gold_ball_jackpot_million", gb.get("jackpot_million"))
            txt="GOLD BALL\n\nThis is NOT predicted by the number model because the 10-digit Gold Ball number is assigned by the lottery system.\n"
            txt += "Only the current official prize-ball state/probability is shown.\n\n"
            txt += f"Balls remaining: {balls if balls is not None else '—'}\n"
            if balls: txt += f"Conditional probability the selected Gold Ball winner receives the jackpot: 1 / {balls} = {100/balls:.3f}%\n"
            txt += f"Current Gold Ball jackpot: ${jackpot} million\n" if jackpot else "Current Gold Ball jackpot: —\n"
            txt += "Per-play Gold Ball odds also depend on the number of issued Gold Ball selections; no sales count is invented.\n"
        elif key=="weights":
            txt="WEIGHT SYSTEM\n\n"
            pw=state.get("pweights",{}); cw=state.get("cweights",{})
            txt += f"{'Factor':16s} {'Production':>12s} {'Challenger':>12s}\n"
            for k in pw:
                txt += f"{k:16s} {100*pw[k]:11.2f}% {100*cw.get(k,0):11.2f}%\n"
            learn=state.get("learning")
            if learn:
                txt += "\nLatest adaptive update: prediction-vs-actual factor/hit correlation.\n"
                try:
                    sig=json.loads(learn.get("signal_json") or "{}")
                    for k,v in sig.items(): txt += f"  {k:14s} signal {v:+.3f}\n"
                except Exception: pass
            txt += "\nMonte Carlo is a diagnostic percentile only and has 0% prediction weight; the six predictive factors are renormalized to 100%."
            txt += "\nProduction changes only through the Promotion Gate. Challenger changes are small and bounded."
        elif key=="learning":
            perf=state.get("performance")
            txt="LEARNING CENTER — CHAMPION MATCH + EXISTING ADAPTIVE LEARNING\n\n"
            if perf:
                txt += f"Production-Challenger paired draws: {perf.get('n',0)}\nProduction avg hit: {perf.get('pavg','—')}\nChallenger avg hit: {perf.get('cavg','—')}\nRandom expected hit/ticket: {perf.get('random','—')}\n"
                txt += f"Challenger - Production: {perf.get('edge','—')}\nPromotion z-score: {perf.get('z','—')}\nPromotion gate: {perf.get('gate','NOT READY')}\n"
            else:
                txt += "No paired Production/Challenger judgments yet. Predictions are frozen before each draw and judged after results arrive.\n"

            snap=state.get("current_draw") or {}
            result=snap.get("result")
            leaders=snap.get("match_leaders") or []
            rec=None
            diag=None
            title=None
            if result and leaders:
                rec=self.app.db.champion_learning_for_date(self.game_key,snap.get('draw_date'),prefix="P")
                diag=((rec or {}).get('record') or {})
                if not diag:
                    diag={
                        "draw_date":snap.get('draw_date'), "actual":result.get('numbers') or [],
                        "actual_bonus":result.get('bonus'), "best_hit":snap.get('best_hit'),
                        "portfolio_size":snap.get('top_n'), "top_n_coverage":snap.get('top_n_coverage'),
                        "selection_miss":snap.get('selection_miss'), "portfolio_miss":snap.get('selection_miss'),
                        "combination_gap":snap.get('combination_gap'),
                        "winner_concentration_efficiency":snap.get('winner_concentration_efficiency'),
                        "ticket_slots":snap.get('ticket_slots'), "portfolio_unique_numbers":snap.get('portfolio_unique_numbers'),
                        "number_pool_size":snap.get('number_pool_size'), "rank_concentration":snap.get('rank_concentration') or {},
                        "candidate_number_ranking":snap.get('candidate_number_ranking') or {},
                        "bottleneck":snap.get('bottleneck'), "leaderboard":leaders,
                        "champions":snap.get('champions') or [],
                        "champion_best_original_rank":snap.get('champion_best_original_rank'),
                        "champion_score_percentile":snap.get('champion_score_percentile'),
                        "score_hit_spearman":snap.get('score_hit_spearman'),
                        "ranking_diagnosis":snap.get('ranking_diagnosis'),
                        "stage_diagnosis":snap.get('stage_diagnosis') or {},
                    }
                title="CURRENT DRAW MATCH LEADERBOARD / 当期开奖命中排行"
            else:
                latest=state.get("champion_latest") or {}
                diag=latest.get("record") or None
                if diag:
                    title="LATEST EVALUATED MATCH LEADERBOARD / 最近一期命中排行"

            if diag:
                txt += "\n" + title + "\n"
                txt += f"Draw: {diag.get('draw_date') or (rec or {}).get('draw_date','—')}   Winning: {fmt_numbers(diag.get('actual') or [])}   Bonus: {diag.get('actual_bonus','—')}\n"
                txt += (f"Max Match: {diag.get('best_hit')}/{self.cfg.pick}   "
                        f"Portfolio winner coverage: {diag.get('top_n_coverage')}/{self.cfg.pick}   "
                        f"Unique numbers: {diag.get('portfolio_unique_numbers','—')}/{diag.get('number_pool_size',self.cfg.max_number)}   "
                        f"Ticket slots: {diag.get('ticket_slots','—')}\n")
                unique_n = diag.get('portfolio_unique_numbers')
                pool_n = diag.get('number_pool_size', self.cfg.max_number)
                try:
                    full_pool = int(unique_n) >= int(pool_n)
                except Exception:
                    full_pool = bool(diag.get('full_pool_coverage'))
                if full_pool:
                    txt += "Coverage interpretation: FULL-POOL COVERAGE — NOT NUMBER-SELECTION EVIDENCE\n"
                txt += (f"Portfolio miss: {diag.get('portfolio_miss',diag.get('selection_miss'))}   "
                        f"Combination gap: {diag.get('combination_gap')}   "
                        f"WCE: {100*float(diag.get('winner_concentration_efficiency',0) or 0):.1f}%   "
                        f"Primary diagnostic: {diag.get('bottleneck','—')}\n")
                rc=(diag.get('rank_concentration') or {}).get('by_k') or {}
                if rc:
                    txt += "Cumulative Winning Coverage: " + "  ".join(
                        f"CWC@{k}={rc[k].get('cumulative_winner_coverage')}/{self.cfg.pick}" for k in ("3","5","10","20") if k in rc) + "\n"
                    txt += "Best Ticket by rank window: " + "  ".join(
                        f"BestHit@{k}={rc[k].get('best_ticket_hit')}/{self.cfg.pick}" for k in ("3","5","10","20") if k in rc) + "\n"
                cand=diag.get('candidate_number_ranking') or {}
                if cand.get('available'):
                    byk=cand.get('by_k') or {}
                    txt += "Pre-draw candidate-number rank: " + "  ".join(
                        f"@{k}={byk[k].get('winner_coverage')}/{self.cfg.pick}" for k in ("10","15","20") if k in byk) + "\n"
                else:
                    txt += "Pre-draw candidate-number rank: unavailable for legacy freeze.\n"
                if diag.get('champion_best_original_rank') is not None:
                    rho = float(diag.get('score_hit_spearman',0) or 0.0)
                    assoc = classify_rank_association(rho)
                    txt += (f"Best-hit placement: {diag.get('ranking_diagnosis','—')} "
                            f"(#{diag.get('champion_best_original_rank')}/{diag.get('portfolio_size','—')})   "
                            f"Score percentile: {diag.get('champion_score_percentile','—')}%\n")
                    txt += f"Global rank association: {assoc}   Spearman: {rho:+.3f}\n"
                    txt += "Score percentile direction: higher = stronger pre-draw Combination Score rank. / 分位越高 = 开奖前评分排名越靠前。\n"
                stages=diag.get('stage_diagnosis') or {}
                if stages:
                    placement_stage = stages.get('best_hit_placement')
                    if not placement_stage:
                        placement_stage = ("GOOD" if diag.get('ranking_diagnosis') == "WELL_RANKED" else
                                           "WEAK" if diag.get('ranking_diagnosis') == "UNDER_RANKED" else "MIXED")
                    association_stage = stages.get('global_rank_association') or classify_rank_association(diag.get('score_hit_spearman'))
                    txt += ("Stage diagnosis: "
                            f"NumberSelection={stages.get('number_selection','—')}  PortfolioCoverage={stages.get('portfolio_coverage','—')}  "
                            f"Concentration={stages.get('combination_concentration','—')}\n")
                    txt += ("Ranking diagnosis: "
                            f"BestHitPlacement={placement_stage}  GlobalAssociation={association_stage}\n")
                txt += "\n"
                txt += f"{'Rank':>4s}  {'Main combination':20s} {'Hit':>5s}  {'Matched':18s} {'Bonus':>6s} {'Score':>7s}\n"
                full=diag.get('leaderboard') or []
                for r in full[:20]:
                    bmark="B✓" if r.get('bonus_hit') is True else ("B×" if r.get('bonus_hit') is False else "B—")
                    nums=fmt_numbers(r.get('numbers') or [])
                    hitnums=fmt_numbers(r.get('matched_numbers') or []) or "—"
                    txt += f"#{int(r.get('rank',0)):>3}  {nums:20s} {int(r.get('main_hits',0)):>2}/{self.cfg.pick:<2}  {hitnums:18s} {bmark:>6s} {float(r.get('score',0)):7.2f}\n"

                champs=diag.get('champions') or []
                if champs:
                    txt += "\nCHAMPION POOL / 最高命中组\n"
                    for c in champs:
                        txt += (f"  #{int(c.get('rank',0))}: {fmt_numbers(c.get('numbers') or [])}  "
                                f"=> {int(c.get('main_hits',0))}/{self.cfg.pick}, matched {fmt_numbers(c.get('matched_numbers') or [])}\n")

            cs=state.get("champion_summary") or {}
            txt += "\nCHAMPION SHADOW LEARNING / 冠军影子学习\n"
            n=int(cs.get('n',0) or 0)
            min_n=int(cs.get('min_samples',CHAMPION_CALIBRATION_MIN_SAMPLES) or CHAMPION_CALIBRATION_MIN_SAMPLES)
            txt += f"Production Champion samples: {n}/{min_n}   Calibration: {cs.get('calibration','WAITING')}\n"
            txt += "Production influence: 0% — Champion learning is isolated until enough out-of-sample evidence exists.\n"
            if n:
                txt += (f"Avg best hit: {cs.get('avg_best_hit','—')}   Avg Top-N coverage: {cs.get('avg_coverage','—')}   "
                        f"Avg selection miss: {cs.get('avg_selection_miss','—')}   Avg combination gap: {cs.get('avg_combination_gap','—')}   "
                        f"Avg WCE: {100*float(cs.get('avg_winner_concentration_efficiency',0) or 0):.1f}%\n")
                txt += (f"Avg Champion original rank: {cs.get('avg_champion_rank','—')}   "
                        f"Avg Score-vs-Hit Spearman: {cs.get('avg_score_hit_spearman','—')}   "
                        f"Under-ranked draws: {cs.get('under_ranked_count',0)}\n")
                if cs.get('bottlenecks'):
                    txt += "Bottlenecks: " + ", ".join(f"{k}={v}" for k,v in cs.get('bottlenecks',{}).items()) + "\n"
                rolling=cs.get('rolling') or {}
                for window in ("20","50"):
                    rw=rolling.get(window) or {}
                    if int(rw.get('n',0) or 0):
                        cwc=rw.get('avg_cwc_at') or {}; bh=rw.get('avg_best_hit_at') or {}; cand=rw.get('avg_candidate_number_coverage_at') or {}
                        txt += f"Rolling {window} ({rw.get('n')} draws): Avg WCE={100*float(rw.get('avg_wce') or 0):.1f}%  Avg gap={rw.get('avg_combination_gap','—')}  Avg Champion rank={rw.get('avg_champion_rank','—')}  Avg Spearman={float(rw.get('avg_spearman') or 0):+.3f}\n"
                        txt += "  CWC " + "  ".join(f"@{k}={cwc.get(k,'—')}" for k in ("3","5","10","20")) + "\n"
                        txt += "  BestHit " + "  ".join(f"@{k}={bh.get(k,'—')}" for k in ("3","5","10","20")) + "\n"
                        if any(cand.get(k) is not None for k in ("10","15","20")):
                            txt += "  Candidate# " + "  ".join(f"@{k}={cand.get(k,'—')}" for k in ("10","15","20")) + "\n"
                txt += "Champion vs non-champion pre-draw component deltas (points):\n"
                for factor,delta in cs.get('strongest_component_deltas',[])[:6]:
                    txt += f"  {factor:12s} {float(delta):+7.3f}\n"
                csw=state.get('champion_shadow_weights') or {}
                if csw:
                    txt += f"Champion Shadow weights {state.get('champion_shadow_version','—')} (research only):\n"
                    for k,v in csw.items():
                        if k!='monte_carlo':
                            txt += f"  {k:12s} {100*float(v):6.2f}%\n"

            pl=state.get("portfolio_learning_status") or {}
            pv=state.get("portfolio_validation") or {}
            txt += "\nV1.5 PORTFOLIO DECISION MEMORY / 预算组合决策记忆\n"
            txt += (f"Forward portfolio draws: {pl.get('n',0)}   Phase: {pl.get('phase','DATA_COLLECTION')}   "
                    f"Confidence: {pl.get('confidence','VERY LOW')}   Production impact: {pl.get('production_impact',0)}%\n")
            sig=pl.get('signal') or {}
            if sig:
                txt += "Shadow policy regret-learning signals (one sample per draw):\n"
                for k,v in sig.items(): txt += f"  {k:18s} {float(v):+8.4f}\n"
            if pv.get('n',0):
                txt += (f"Shadow - Production avg-hit edge: {pv.get('shadow_minus_production_avg_hit','—')}   "
                        f"p={pv.get('shadow_edge_p_two_sided','—')}   Prod-vs-Random edge={pv.get('production_vs_random_best_hit_edge','—')}\n")
            txt += "The learning engine stores pre-draw rationale, post-draw result, same-budget Random control and counterfactual regret. It never counts subset count as sample size.\n"
            pll=state.get("portfolio_line_learning") or {}
            txt += "\nPER-LINE LEARNING / 单组分开学习\n"
            txt += (f"Effective draws: {pll.get('n',0)}   Phase: {pll.get('phase','DATA_COLLECTION')}   "
                    f"Mean replaceable fraction: {pll.get('mean_replaceable_fraction','—')}   Production impact: {pll.get('production_impact',0)}%\n")
            roles=pll.get('by_role') or {}
            if roles:
                txt += "Role performance (draw-level aggregation; lines are NOT independent samples):\n"
                for role,item in sorted(roles.items()):
                    txt += (f"  {role:10s} draws={int(item.get('draws',0)):>3}  "
                            f"mean hit/line={item.get('mean_hits_per_selected_line','—')}  "
                            f"unique winner contribution={item.get('mean_unique_winner_contribution','—')}  "
                            f"draw-level prize rate={item.get('mean_draw_level_prize_rate','—')}\n")
            bands=pll.get('by_rank_band') or {}
            if bands:
                txt += "Rank-band performance:\n"
                for band,item in sorted(bands.items()):
                    txt += (f"  #{band:5s} draws={int(item.get('draws',0)):>3}  "
                            f"mean hit/line={item.get('mean_hits_per_selected_line','—')}  "
                            f"unique winner contribution={item.get('mean_unique_winner_contribution','—')}\n")
            txt += "Per-line learning stays Shadow-only until enough forward draws accumulate; it cannot rewrite past freezes.\n"

            v14=state.get("v14_validation") or {}
            trade=(v14.get("coverage_tradeoff") or {})
            txt += "\nV1.4 COVERAGE ↔ CONCENTRATION MONITOR / 覆盖与集中度监控\n"
            txt += (f"Paired draws: {trade.get('n',0)}   "
                    f"Balanced coverage gain vs Score-only: {trade.get('balanced_coverage_gain_vs_score_only','—')}   "
                    f"Concentration cost: {trade.get('balanced_concentration_cost_vs_score_only','—')}\n")
            if not trade.get('n',0):
                txt += "Starts with the next V1.4 pre-draw freeze; past draws are not post-draw regenerated for this comparison.\n"
            scorecmp=((v14.get("comparisons") or {}).get("score_only") or {})
            if scorecmp.get("n",0):
                txt += (f"Score-only avg-hit delta vs Balanced: {scorecmp.get('avg_hit_delta','—')}   "
                        f"95% CI [{(scorecmp.get('avg_hit_ci95') or {}).get('low','—')}, {(scorecmp.get('avg_hit_ci95') or {}).get('high','—')}]   "
                        f"FDR q={scorecmp.get('fdr_q','—')}   Gate={scorecmp.get('gate','—')}\n")

            txt += f"\nNumber Neural Shadow: {state.get('nn_status','—')}\n"
            txt += f"Region Neural Shadow: {state.get('region_nn_status','—')}\n"
            rnp=state.get("region_nn_prediction") or {}
            if rnp:
                txt += "Region NN next-structure shadow prediction:\n"
                for k,v in rnp.items(): txt += f"  {k:6s}: {v.get('label')}  shadow confidence={v.get('shadow_confidence')}\n"
            txt += "All neural and Champion Shadow Production weights: 0%\n"
        elif key=="research":
            txt="V1.4 MODEL VALIDATION LAB — SHADOW ONLY\n\n"
            txt += "Production numbers are never changed by this page. Sharing Risk and Monte Carlo diagnostics both have 0% ranking weight. Ablation and Rank Stability are research-only diagnostics.\n\n"
            txt += "MONTE CARLO POLICY\nDiagnostic percentile only: 0% Production/Challenger ranking weight. It cannot reward a combination twice for the same underlying score.\n\n"
            reg=state.get("regime") or {}
            txt += "REGIME ENGINE\n"
            txt += f"Current regime: {reg.get('current_regime','—')}  |  pool {reg.get('pool','—')}  |  start {reg.get('regime_start','—')}\n"
            txt += f"Current-regime usable draws: {reg.get('production_draws','—')}  |  sample state: {reg.get('sample_state','—')}\n"
            if reg.get('all_regime_counts'):
                txt += "Archive by regime: " + ", ".join(f"{k}={v}" for k,v in reg.get('all_regime_counts',{}).items()) + "\n"
            txt += f"Neural gate: {reg.get('neural_gate','—')}\n"
            devs=reg.get('strongest_normalized_deviations') or []
            if devs:
                txt += "Largest regime-normalized descriptive deviations (NOT proof of edge):\n"
                for d in devs[:5]:
                    txt += f"  {int(d['number']):02d}: z={float(d['z']):+.2f}, eligible={d['eligible_draws']}, obs/exp={d['observed_expected_ratio']:.3f}\n"
            txt += "\nRANDOM CONTROL\n"
            txt += f"Status: {state.get('random_status','WAITING')}\n"
            txt += "No historical features; deterministic pre-draw seed; diversity-matched only for fair portfolio comparison.\n"
            txt += "\nSHARING-RISK PROXY — ADVISORY ONLY / 共享风险 — 仅供参考\n"
            txt += "Human-selection proxy only: birthday/date-heavy patterns, obvious sequences, repeated endings/gaps.\n"
            txt += "Prediction ranking contribution: 0%. It never removes, demotes or promotes a Main combination.\n"
            txt += "It can describe possible prize-sharing pressure if a ticket wins; it does NOT change draw probability.\n"
            txt += "\nPORTFOLIO OPTIMIZER\n"
            txt += f"Status: {state.get('research_status','WAITING')}\n"
            ps=state.get('research_portfolio_summary') or {}
            if ps:
                txt += f"Tickets: {ps.get('tickets')}  |  unique numbers: {ps.get('unique_numbers')} ({ps.get('pool_coverage_pct')}% of pool)\n"
                txt += f"Avg overlap: {ps.get('avg_pair_overlap')}  |  max overlap: {ps.get('max_pair_overlap')}  |  diversity: {ps.get('diversity_score')}\n"
                txt += f"Mean crowd avoidance: {ps.get('mean_crowd_avoidance')}  |  high-crowd tickets: {ps.get('high_crowd_risk_tickets')}\n"
            rp=state.get('research_preds') or []
            if rp:
                txt += "Research portfolio preview (first 4):\n"
                for r in rp[:4]:
                    txt += f"  #{r.get('rank',0):>2} {fmt_numbers(r.get('numbers',[]))}  Research {float(r.get('research_score',r.get('score',0))):.2f}  SharingRisk {r.get('crowd_risk','—')} (0% weight)  Regime {float(r.get('regime_score',50)):.1f}\n"
            txt += "\nV1.4 SAME-BUDGET STRATEGY SHADOWS / 同预算策略影子组\n"
            ss=state.get("v14_strategy_status") or {}
            txt += "  " + "  |  ".join(f"{k}={ss.get(k,'WAITING')}" for k in ("balanced","score_only","focused","pure_coverage","concentrated")) + "\n"
            txt += "New official predictions freeze five same-candidate strategies, including Concentrated as a research-only control; none can auto-replace Production. Older-version upgrade bridges are flagged as not sharing the original Production pool.\n"
            integ=state.get("freeze_integrity") or {}
            if integ.get('status') == 'NO_FREEZE' and state.get('target'):
                txt += f"Production freeze integrity: NOT CREATED YET (target {state.get('target')})\n"
            else:
                txt += f"Production freeze integrity: {integ.get('status','—')}\n"
            ilayers=integ.get("layers") or {}
            if ilayers:
                txt += ("  Layers: "
                        f"Prediction={((ilayers.get('prediction') or {}).get('status','—'))}  |  "
                        f"Features={((ilayers.get('feature_snapshot') or {}).get('status','—'))}  |  "
                        f"Algorithm={((ilayers.get('algorithm') or {}).get('status','—'))}  |  "
                        f"CandidatePool={((ilayers.get('candidate_pool') or {}).get('status','—'))}\n")
            if integ.get('candidate_pool_sha256'):
                txt += f"  Candidate pool digest: {str(integ.get('candidate_pool_sha256'))[:12]}… (provenance only unless an independent pool snapshot exists)\n"

            v14=state.get("v14_validation") or {}
            trade=v14.get("coverage_tradeoff") or {}
            txt += "\nCOVERAGE ↔ CONCENTRATION TRADE-OFF / 覆盖与集中度权衡\n"
            txt += (f"Paired Balanced-vs-Score-only draws: {trade.get('n',0)} | "
                    f"Balanced Coverage Gain: {trade.get('balanced_coverage_gain_vs_score_only','—')} | "
                    f"Concentration Cost: {trade.get('balanced_concentration_cost_vs_score_only','—')}\n")
            txt += "Positive Coverage Gain means Balanced covered more winning numbers. Positive Concentration Cost means Score-only produced a better single-ticket match.\n"
            if not trade.get('n',0):
                txt += "No retroactive post-draw strategy generation is counted. The paired monitor begins when V1.4 freezes the strategies before a future draw.\n"

            comps=v14.get("comparisons") or {}
            if comps:
                txt += "\nSTATISTICAL VALIDATION / 统计验证 (paired, out-of-sample frozen only)\n"
                txt += f"{'Strategy':18s} {'n':>4s} {'AvgΔ':>8s} {'BestΔ':>8s} {'CovΔ':>8s} {'CI95':>22s} {'FDR q':>9s} {'Gate':>20s}\n"
                for label in ("balanced_shadow","score_only","focused","pure_coverage"):
                    c=comps.get(label) or {}
                    ci=c.get('avg_hit_ci95') or {}
                    ci_text=(f"[{ci.get('low')},{ci.get('high')}]" if ci.get('low') is not None else "—")
                    txt += (f"{label:18s} {int(c.get('n',0)):4d} {float(c.get('avg_hit_delta',0)):+8.4f} "
                            f"{float(c.get('best_hit_delta',0)):+8.4f} {float(c.get('coverage_delta',0)):+8.4f} "
                            f"{ci_text:>22s} {str(c.get('fdr_q','—')):>9s} {str(c.get('gate','—')):>20s}\n")
                txt += "Bootstrap CI + paired sign-flip permutation test + Benjamini-Hochberg FDR. Screening/confirmation are research gates, not proof of lottery predictability.\n"
                txt += "Rolling deltas (strategy - Production):\n"
                for label in ("score_only","focused","pure_coverage"):
                    c=comps.get(label) or {}; roll=c.get('rolling') or {}
                    bits=[]
                    for w in ("30","50","100"):
                        r=roll.get(w) or {}
                        if r.get('n'):
                            bits.append(f"{w}D n={r.get('n')} avgΔ={r.get('avg_hit_delta'):+.3f} bestΔ={r.get('best_hit_delta'):+.3f} covΔ={r.get('coverage_delta'):+.3f}")
                    if bits:
                        txt += f"  {label}: " + " | ".join(bits) + "\n"

            perf=state.get('performance') or {}
            txt += "\nFORWARD SCORECARD\n"
            txt += f"Production vs Random frozen pairs: {perf.get('rnd_n',0)}"
            if perf.get('rnd_n',0):
                txt += f"  |  P-RND avg-hit edge {perf.get('prod_vs_rnd','—')}  |  z {perf.get('rnd_z','—')}  |  {perf.get('rnd_gate','NOT READY')}"
            txt += "\n"
            txt += f"Production vs Research frozen pairs: {perf.get('res_n',0)}"
            if perf.get('res_n',0):
                txt += f"  |  RES-P avg-hit delta {perf.get('res_vs_prod','—')}  |  z {perf.get('res_z','—')}  |  {perf.get('res_gate','NOT READY')}"
            txt += "\nGate policy: SCREENING uses paired sample-SD t critical; CONFIRMATION requires n>=200 and a stricter threshold. Repeated monitoring is not proof of predictive edge. / 门槛策略：筛选信号不等于确认信号，持续观察不代表已证明预测优势。"
            bayes=state.get("bayesian_strategy") or {}
            txt += "\n\nBAYESIAN STRATEGY EVALUATOR / 分层贝叶斯策略评估器\n"
            if bayes.get("status") != "READY":
                txt += "No Bayesian strategy evidence yet. Run Research + Bayesian Lab first. / 尚无贝叶斯策略证据，请先运行研究实验室。\n"
            else:
                txt += (f"Historical walk-forward draws: {bayes.get('historical_draws',0)} (weight {bayes.get('historical_discount','—')}) | "
                        f"Forward frozen draws: {bayes.get('forward_draws',0)} (weight 1.0) | "
                        f"Production impact: {bayes.get('production_impact',0)}%\n")
                leader=bayes.get("research_leader")
                if leader:
                    lead=(bayes.get("variants") or {}).get(leader) or {}
                    ci=lead.get("credible_interval_95") or {}
                    effn=float(lead.get('effective_n',0) or 0)
                    txt += (f"Research leader: {leader} | posterior edge {float(lead.get('posterior_mean_edge',0)):+.4f} | "
                            f"P(edge>0) {100*float(lead.get('probability_edge_positive',0)):.1f}% | "
                            f"CI95 [{ci.get('low','—')},{ci.get('high','—')}] | {lead.get('gate','—')}\n")
                    if effn < 30:
                        txt += f"⚠ LOW SAMPLE: leader effective n={effn:.1f}; posterior estimates are highly unstable and descriptive only.\n"
                txt += f"{'Variant':22s} {'Hist':>5s} {'Fwd':>5s} {'EffN':>6s} {'PostEdge':>10s} {'P>0':>7s} {'CI95':>23s} {'Consistency':>14s} {'Gate':>22s}\n"
                for label in (bayes.get("ranking") or [])[:12]:
                    item=(bayes.get("variants") or {}).get(label) or {}
                    ci=item.get("credible_interval_95") or {}
                    ci_text=f"[{ci.get('low','—')},{ci.get('high','—')}]"
                    txt += (f"{label:22s} {int((item.get('historical') or {}).get('n',0)):5d} "
                            f"{int((item.get('forward') or {}).get('n',0)):5d} {float(item.get('effective_n',0)):6.1f} "
                            f"{float(item.get('posterior_mean_edge',0)):+10.4f} "
                            f"{100*float(item.get('probability_edge_positive',0)):6.1f}% {ci_text:>23s} "
                            f"{str(item.get('source_consistency','—')):>14s} {str(item.get('gate','—')):>22s}\n")
                txt += "Historical evidence is discounted; only pre-draw forward freezes can reach confirmation. One draw is always one effective sample.\n"
                txt += "This evaluator cannot change Production or authorize automatic spending. / 本评估器不能修改正式模型，也不能授权自动投注。\n"
            txt += "\n\nMAIN-BONUS CONSISTENCY / 主号-特别号一致性\n"
            cur=state.get("main_bonus_consistency") or {}
            hist=state.get("main_bonus_audit") or {}
            txt += (f"Current frozen/display binding: {cur.get('status','—')} | "
                    f"bound {cur.get('bound_main_picks',0)}/{cur.get('total_main_picks',0)} | errors {len(cur.get('errors') or [])}\n")
            txt += (f"Historical freeze audit: {hist.get('status','—')} | freezes {hist.get('checked_freezes',0)} | "
                    f"bindings {hist.get('checked_bindings',0)} | legacy partial {hist.get('legacy_partial_freezes',0)} | "
                    f"non-legacy partial {hist.get('nonlegacy_partial_freezes',0)} | errors {len(hist.get('errors') or [])} | "
                    f"warnings {len(hist.get('warnings') or [])}\n")
            txt += "Bonus Conditional Score is isolated from Main Combination ranking. / 特别号条件评分与主号组合排名完全隔离。\n\n"
            res=state.get("research")
            if not res:
                txt += "Historical placebo tests have not been run in this session.\n"
            else:
                abl=res.get("feature_ablation") or {}
                stab=res.get("rank_stability") or {}
                txt += "MODEL QUALITY DIAGNOSTICS / 模型质量诊断\n"
                if abl.get("status") == "ok":
                    flags=[x.get("factor") for x in (abl.get("factors") or []) if x.get("screen") == "INVESTIGATE"]
                    txt += (f"Feature ablation: n={abl.get('n')} sample={abl.get('sample_state')} | "
                            f"full avg hit={abl.get('full_avg_hit')} | review flags={', '.join(flags) if flags else 'none'}\n")
                else:
                    txt += f"Feature ablation: {abl.get('status','not run')} (have {abl.get('have','—')}, need {abl.get('needed','—')})\n"
                if stab.get("status") == "ok":
                    txt += (f"Rank stability: {stab.get('stability')} | ticket retention={stab.get('ticket_retention_pct')}% | "
                            f"number-pool Jaccard={stab.get('number_pool_jaccard_pct')}% | top-1 retention={stab.get('top1_retention_pct')}%\n")
                else:
                    txt += f"Rank stability: {stab.get('status','not run')} (have {stab.get('have','—')}, need {stab.get('needed','—')})\n"
                covtest=res.get("coverage_strategy") or {}
                if covtest.get("status") == "ok":
                    st=covtest.get("strategies") or {}
                    bal=st.get("balanced") or {}; top=st.get("score_only") or {}; pure=st.get("pure_coverage") or {}
                    txt += (f"Coverage same-budget shadow: n={covtest.get('n')} lines={covtest.get('same_budget_lines')} | "
                            f"Balanced avg hit={bal.get('avg_hit','—')} CE={bal.get('coverage_efficiency','—')} | "
                            f"TopScore avg hit={top.get('avg_hit','—')} CE={top.get('coverage_efficiency','—')} | "
                            f"PureCoverage avg hit={pure.get('avg_hit','—')} CE={pure.get('coverage_efficiency','—')}\n")
                else:
                    txt += f"Coverage same-budget shadow: {covtest.get('status','not run')}\n"
                txt += "These diagnostics do not auto-change Production weights. / 这些诊断不会自动修改正式模型权重。\n\n"
                txt += "HISTORICAL / PLACEBO TESTS\n" + json.dumps(res, indent=2, ensure_ascii=False)
            txt += "\n\nUse 'Freeze Shadow Suite' before the target draw, then 'Run Research Tests' for ablation, stability and historical diagnostics."
        elif key=="data":
            txt="DATA STATUS\n\n"
            hh=state.get("history_health") or {}
            txt += f"Database rows: {state.get('count',0)}\n"
            txt += f"Unique draw dates: {hh.get('unique_dates','—')}\n"
            txt += f"Model-ready archive draws: {hh.get('model_ready_archive_draws','—')}\n"
            txt += f"Current model-era usable draws: {hh.get('model_era_draws','—')} / expected {hh.get('model_era_expected','—')}  |  Era coverage: {hh.get('model_era_coverage_pct','—')}%\n"
            txt += f"Expected draw dates: {hh.get('expected','—')}  |  Calendar: {hh.get('calendar_source','—')}\n"
            if hh.get('provisional_special_draws'):
                txt += (f"Official-verified special dates carried into fallback calendar: "
                        f"{hh.get('provisional_special_draws')}"
                        + (" (" + ", ".join(hh.get('provisional_special_dates', [])[-6:]) + ")" if hh.get('provisional_special_dates') else "") + "\n")
            txt += (f"Coverage: {hh.get('coverage_pct','—')}%  |  Raw audit pass ratio: {hh.get('integrity_score','—')}% "
                    f"[{hh.get('status','—')}]\n")
            txt += "Raw audit pass ratio measures stored rows free of invalid/unverified-off-calendar/conflict flags; it is not a probability that the archive is correct.\n"
            txt += (f"Model integrity: {hh.get('usable_integrity_score','—')}%  |  "
                    f"Model data: {hh.get('model_data_status','—')}\n")
            mba=state.get("main_bonus_audit") or {}
            txt += (f"Main-Bonus consistency audit / 主号-特别号一致性审计: {mba.get('status','—')} | "
                    f"freezes {mba.get('checked_freezes',0)} | legacy partial {mba.get('legacy_partial_freezes',0)} | "
                    f"non-legacy partial {mba.get('nonlegacy_partial_freezes',0)} | errors {len(mba.get('errors') or [])} | "
                    f"warnings {len(mba.get('warnings') or [])}\n")
            txt += f"Missing scheduled: {hh.get('missing','—')}  |  Unexpected: {hh.get('unexpected','—')}  |  Invalid: {hh.get('invalid','—')}  |  Conflicts: {hh.get('conflicts','—')}\n"
            txt += f"Model exclusions/quarantine: {len(hh.get('model_exclusions',[]) or [])}\n"
            if hh.get('missing_sample'):
                txt += "Missing sample: " + ", ".join(hh.get('missing_sample')[-6:]) + "\n"
            if hh.get('unexpected_sample'):
                txt += "Unexpected sample: " + ", ".join(hh.get('unexpected_sample')[-6:]) + "\n"
            if hh.get('unexpected_classes'):
                txt += "Unexpected classification: " + ", ".join(f"{k}={v}" for k,v in sorted(hh.get('unexpected_classes',{}).items())) + "\n"
            if hh.get('shifted_duplicates'):
                txt += f"Likely one-day duplicate shifts: {hh.get('shifted_duplicates')}"
                if hh.get('shifted_duplicate_dates'):
                    txt += " (" + ", ".join(hh.get('shifted_duplicate_dates')[-6:]) + ")"
                if hh.get('strong_shifted_duplicates'):
                    txt += f" | exact main+bonus: {hh.get('strong_shifted_duplicates')}"
                txt += "\n"
            details = hh.get('unexpected_details') or []
            if details:
                txt += "Unexpected provenance:\n"
                for item in details[-6:]:
                    src = item.get('source') or 'unknown'
                    extra = f" -> duplicate of {item.get('shift_duplicate_of')}" if item.get('shift_duplicate_of') else ""
                    strength = f" [{item.get('shift_strength')}]" if item.get('shift_strength') else ""
                    cls_name = item.get('classification') or 'UNCLASSIFIED'
                    txt += f"  {item.get('date')}: {src} [{cls_name}]{extra}{strength}\n"
            if hh.get('conflict_dates'):
                txt += "Conflict sample: " + ", ".join(hh.get('conflict_dates')[-6:]) + "\n"
            txt += f"Data folder: {DATA_DIR}\nLast update: {self.app.db.get_state('last_update','—')}\n"
            if state.get("latest"):
                txt += f"Latest source: {state['latest'].get('source')}\nVerified: {state['latest'].get('verified')}\n"
            rep=self.app.db.get_state("last_update_report",{}) or {}
            if rep:
                txt += f"Latest update: {rep.get('latest_status',rep.get('status','—'))}\n"
                txt += f"History status: {rep.get('history_status','—')}\n"
                txt += f"Source redundancy: {rep.get('redundancy_status','—')}\n"
                txt += f"Completed: {rep.get('finished_at','—')}\n"
                g=(rep.get('games') or {}).get(self.game_key,{})
                latestrep=g.get('latest') or {}
                for name,st in (latestrep.get('sources') or {}).items():
                    optional=" (optional)" if st.get('optional') else ""
                    txt += f"  {name}: {'OK' if st.get('ok') else 'FAIL'}{optional}" + (f" ({st.get('error')})" if st.get('error') else "") + "\n"
                hist=g.get('history') or {}
                for name,st in (hist.get('sources') or {}).items():
                    if st.get('skipped'):
                        txt += f"  History/{name}: SKIPPED ({st.get('reason','not needed')})\n"
                    else:
                        txt += f"  History/{name}: {'OK' if st.get('ok') else 'FAIL'}" + (f" ({st.get('draws',0)} draws)" if st.get('ok') else f" ({st.get('error')})") + "\n"
                    if name == "WCLC since inception" and st.get('ok'):
                        txt += f"    Official archive: {st.get('archive_draws','—')} rows, {st.get('archive_first','—')} → {st.get('archive_last','—')}\n"
                        txt += f"    Calendar accepted: {st.get('calendar_accepted','—')} | schedule coverage through archive cutoff: {st.get('schedule_coverage_through_archive_pct','—')}%\n"
                        txt += f"    Official special/off-schedule dates detected: {st.get('special_draw_dates','—')} | missing before merge: {st.get('official_missing_before_merge','—')}\n"
                    if name == "GitHub CSV":
                        for repo,detail in (st.get('details') or {}).items():
                            if repo == "_summary":
                                if detail.get('conflicts_held_out'):
                                    txt += f"    GitHub conflicts held out: {detail.get('conflicts_held_out')}\n"
                                continue
                            txt += f"    {repo}: {'OK' if detail.get('ok') else 'FAIL'}"
                            if detail.get('ok'):
                                txt += f" ({detail.get('draws',0)} draws)"
                            elif detail.get('error'):
                                txt += f" ({detail.get('error')})"
                            txt += "\n"
                            if detail.get('identity_gate'):
                                txt += (f"      Identity gate: {detail.get('identity_gate')} | "
                                        f"calendar match {detail.get('calendar_compatibility_pct','—')}% | "
                                        f"off-schedule filtered {detail.get('off_schedule_filtered',0)}\n")
                                if detail.get('off_schedule_sample'):
                                    txt += "      Off-schedule sample: " + ", ".join(detail.get('off_schedule_sample')[:6]) + "\n"
            txt += f"Next frozen target: {state.get('target','—')}\n"
            txt += "\nHistory calendar (both games): WCLC since-inception official first; recovery sources are used only for gaps. 6/49 also has National-Lottery fallback."
            txt += "\nLatest official sources (BC priority): WCLC → OLG → Loto-Québec; ALC is an optional cross-check."
            txt += "\n\nPipeline: RAW/Provider → validation → SQLite → features → prediction → freeze → judge → challenger learning."
        self.set_text(self.analysis_text,txt)
        if key=="bonus" and self.analysis_open:
            self.bonus_selector_frame.pack(fill="x", pady=(0,6), before=self.analysis_text)
        else:
            self.bonus_selector_frame.pack_forget()
        if hasattr(self,"freeze_shadow_btn"):
            self.freeze_shadow_btn.configure(text=self.app.t("freeze_shadow"))
            self.run_research_btn.configure(text=self.app.t("run_research"))
        if hasattr(self,"refresh_repair_btn"):
            self.refresh_repair_btn.configure(text=self.app.t("refresh_repair"))
            self.run_audit_btn.configure(text=self.app.t("run_audit"))
            self.import_csv_btn.configure(text=self.app.t("import_csv"))
        if key=="research" and self.analysis_open:
            if not hasattr(self,"research_btn_frame"):
                self.research_btn_frame=ttk.Frame(self.analysis)
                self.freeze_shadow_btn=ttk.Button(self.research_btn_frame,text=self.app.t("freeze_shadow"),command=lambda:self.app.freeze_research_async(self.game_key))
                self.freeze_shadow_btn.pack(side="left")
                self.run_research_btn=ttk.Button(self.research_btn_frame,text=self.app.t("run_research"),command=lambda:self.app.run_research_async(self.game_key))
                self.run_research_btn.pack(side="left",padx=6)
            self.research_btn_frame.pack(anchor="w",pady=(6,0))
        elif hasattr(self,"research_btn_frame"):
            self.research_btn_frame.pack_forget()
        if key=="data" and self.analysis_open:
            if not hasattr(self,"data_btn_frame"):
                self.data_btn_frame=ttk.Frame(self.analysis)
                self.refresh_repair_btn=ttk.Button(self.data_btn_frame,text=self.app.t("refresh_repair"),command=lambda:self.app.repair_history_async(self.game_key))
                self.refresh_repair_btn.pack(side="left")
                self.run_audit_btn=ttk.Button(self.data_btn_frame,text=self.app.t("run_audit"),command=lambda:self.app.audit_history_async(self.game_key))
                self.run_audit_btn.pack(side="left",padx=6)
                self.import_csv_btn=ttk.Button(self.data_btn_frame,text=self.app.t("import_csv"),command=lambda:self.app.import_history_csv(self.game_key))
                self.import_csv_btn.pack(side="left")
            self.data_btn_frame.pack(anchor="w",pady=(6,0))
        elif hasattr(self,"data_btn_frame"):
            self.data_btn_frame.pack_forget()


class LotteryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1040x860")
        self.minsize(900,700)
        self.db=Database(DB_PATH)
        self.language_mode=self.db.get_state("ui_language","bilingual") or "bilingual"
        if self.language_mode not in LANG_LABELS:
            self.language_mode="bilingual"
        self.updater=DataUpdater(self.db)
        self.learning=LearningManager(self.db)
        self.game_state={k:{} for k in GAMES}
        self.nn={k:NeuralShadow(k,MODEL_DIR) for k in GAMES}
        self.region_nn={k:RegionNeuralShadow(k,MODEL_DIR) for k in GAMES}
        self.cards={}
        self._ui_queue=queue.Queue()
        self._update_lock=threading.Lock()
        self._build_ui()
        self.after(50,self._drain_ui_queue)
        self._load_seed_if_needed()
        self.after(200,lambda:self._start_worker(self.startup_pipeline))
        self.after(30*60*1000,self.periodic_update)

    def t(self, key):
        en, zh = UI_TEXT.get(key, (str(key), str(key)))
        if self.language_mode == "en":
            return en
        if self.language_mode == "zh":
            return zh
        return f"{en} / {zh}"

    def _change_language(self, _event=None):
        label=self.language_var.get() if hasattr(self,"language_var") else LANG_LABELS.get(self.language_mode,"中英双语")
        reverse={v:k for k,v in LANG_LABELS.items()}
        self.language_mode=reverse.get(label,"bilingual")
        self.db.set_state("ui_language",self.language_mode)
        if hasattr(self,"language_label"):
            self.language_label.configure(text=self.t("language")+":")
        if hasattr(self,"research_mode_label"):
            if self.language_mode=="en":
                self.research_mode_label.configure(text="Research mode · Combination Score ≠ winning probability · Sharing Risk = advisory only")
            elif self.language_mode=="zh":
                self.research_mode_label.configure(text="研究模式 · 组合评分 ≠ 中奖概率 · 共享风险仅供参考")
            else:
                self.research_mode_label.configure(text="Research mode / 研究模式 · Combination Score / 组合评分 ≠ winning probability / 中奖概率 · Sharing Risk / 共享风险 = advisory only / 仅供参考")
        if hasattr(self,"update_button"):
            self.update_button.configure(text=self.t("update_now"))
        if hasattr(self,"auto_promo_check"):
            self.auto_promo_check.configure(text=self.t("auto_promotion"))
        for card in getattr(self,"cards",{}).values():
            card.refresh()

    def _build_ui(self):
        top=ttk.Frame(self,padding=12)
        top.pack(fill="x")
        ttk.Label(top,text=f"{APP_NAME} {APP_VERSION}",font=("Segoe UI",20,"bold")).pack(side="left")
        self.research_mode_label=ttk.Label(top,text="",foreground="#666")
        self.research_mode_label.pack(side="left",padx=16)
        lang=ttk.Frame(top)
        lang.pack(side="right",padx=(8,0))
        self.language_label=ttk.Label(lang,text=self.t("language")+":")
        self.language_label.pack(side="left")
        self.language_var=tk.StringVar(value=LANG_LABELS.get(self.language_mode,"中英双语"))
        self.language_combo=ttk.Combobox(lang,textvariable=self.language_var,state="readonly",width=10,values=tuple(LANG_LABELS.values()))
        self.language_combo.pack(side="left",padx=(4,0))
        self.language_combo.bind("<<ComboboxSelected>>",self._change_language)
        upd=ttk.Frame(top)
        upd.pack(side="right")
        self.update_button=ttk.Button(upd,text=self.t("update_now"),command=lambda:self._start_worker(self.update_pipeline))
        self.update_button.pack(anchor="e")
        self.update_status_label=ttk.Label(upd,text="Update: —",foreground="#666")
        self.update_status_label.pack(anchor="e",pady=(2,0))
        self.update_time_label=ttk.Label(upd,text="",foreground="#666")
        self.update_time_label.pack(anchor="e")
        self.update_sources_label=ttk.Label(upd,text="",foreground="#666")
        self.update_sources_label.pack(anchor="e")
        self._refresh_update_status()

        container=ttk.Frame(self)
        container.pack(fill="both",expand=True)
        canvas=tk.Canvas(container,highlightthickness=0)
        scroll=ttk.Scrollbar(container,orient="vertical",command=canvas.yview)
        inner=ttk.Frame(canvas,padding=(14,4,14,14))
        inner.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        win=canvas.create_window((0,0),window=inner,anchor="nw")
        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(win,width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")

        for key in ("max","649"):
            card=CollapsibleGameCard(inner,self,key)
            card.pack(fill="x",expand=True,pady=(0,14))
            self.cards[key]=card

        footer=ttk.Frame(inner,padding=8)
        footer.pack(fill="x")
        self.auto_promo=tk.BooleanVar(value=self.db.get_state("auto_promotion",False))
        self.auto_promo_check=ttk.Checkbutton(footer,text=self.t("auto_promotion"),variable=self.auto_promo,command=self._save_settings)
        self.auto_promo_check.pack(side="left")
        ttk.Label(footer,text="Auto data check: every 30 minutes while app is open / 应用开启时每30分钟自动检查数据",foreground="#666").pack(side="right")
        self._change_language()

    def _refresh_update_status(self, status=None, completed=None):
        rep=self.db.get_state("last_update_report",{}) or {}
        if status is None:
            status=rep.get("latest_status",rep.get("status","—"))
            completed=rep.get("finished_at")
        symbol={"SUCCESS":"✓","PARTIAL":"⚠","FAILED":"✗","UPDATING":"…"}.get(str(status).upper(),"•")
        if hasattr(self,"update_status_label"):
            clock=""
            if completed:
                try:
                    clock=format_bc_timestamp(completed)
                except Exception:
                    clock=str(completed)
            self.update_status_label.configure(text=f"{symbol} LATEST {status}" + (f" · {clock}" if clock else ""))
            if status == "UPDATING":
                self.update_time_label.configure(text="Retry/backoff enabled · history repair runs only when due")
                self.update_sources_label.configure(text="BC primary: WCLC → OLG → other official / history fallback")
            else:
                self.update_time_label.configure(text=f"History: {rep.get('history_status','—')} · Redundancy: {rep.get('redundancy_status','—')} · Added {rep.get('total_added',0)}")
                counts={"WCLC":[0,0],"OLG":[0,0],"Loto-Québec":[0,0]}
                for g in (rep.get("games") or {}).values():
                    src=((g.get("latest") or {}).get("sources") or {})
                    for name in counts:
                        if name in src:
                            counts[name][1]+=1
                            counts[name][0]+=1 if src[name].get("ok") else 0
                bits=[]
                for name,label in (("WCLC","WCLC"),("OLG","OLG"),("Loto-Québec","LQ")):
                    ok,total=counts[name]
                    if total: bits.append(f"{label} {ok}/{total}")
                self.update_sources_label.configure(text=" · ".join(bits))

    def _save_settings(self):
        self.db.set_state("auto_promotion",bool(self.auto_promo.get()))

    def _load_seed_if_needed(self):
        if not SEED_PATH.exists(): return
        payload=json.loads(SEED_PATH.read_text(encoding="utf-8"))
        for game,rows in payload.items():
            if self.db.count_draws(game)>0: continue
            for d in rows:
                self.db.upsert_draw(game,d["date"],era_for(game,d["date"]),d["numbers"],d.get("bonus"),d.get("source","Seed"),verified=d.get("verified",False))

    def _ui_call(self, callback):
        """Marshal UI work to the Tk main thread without calling Tk from workers."""
        if hasattr(self, "_ui_queue"):
            self._ui_queue.put(callback)
        elif hasattr(self, "after"):
            # Unit-test / compatibility shell; real app instances always use queue.
            self.after(0, callback)
        else:
            callback()

    def _drain_ui_queue(self):
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                try:
                    callback()
                except Exception:
                    logger.exception("UI callback failed")
        except queue.Empty:
            pass
        self.after(50,self._drain_ui_queue)

    def _start_worker(self,fn):
        threading.Thread(target=self._safe_worker,args=(fn,),daemon=True).start()

    def _safe_worker(self,fn):
        try:
            fn()
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            traceback.print_exc()
            logger.exception("Background worker failed: %s", msg)
            # Worker failures must not leave cards permanently stuck at Updating/Running.
            # Reset the model state first, then refresh cards and show the error in one UI
            # callback so compatibility test shells that retain one callback stay correct.
            for state in getattr(self, "game_state", {}).values():
                if state.get("status") != "Ready":
                    state["status"] = "Ready"
            def recover_ui(m=msg):
                for key, card in getattr(self, "cards", {}).items():
                    try:
                        card.refresh()
                    except Exception:
                        logger.exception("Card refresh failed while recovering worker error: %s", key)
                messagebox.showerror(APP_NAME, m)
            LotteryApp._ui_call(self, recover_ui)

    def startup_pipeline(self):
        # Load any already-frozen official prediction first, then refresh data.
        for key in GAMES:
            self.refresh_game_state(key)
        self.update_pipeline()

    def update_pipeline(self):
        # Startup, manual refresh and the periodic timer can converge on the same
        # moment. Only one update/judgment pipeline may run at a time.
        lock = getattr(self, "_update_lock", None)
        if lock is not None and not lock.acquire(blocking=False):
            self._ui_call(lambda: self._refresh_update_status("UPDATE ALREADY RUNNING", None))
            return
        try:
            return self._update_pipeline_body()
        finally:
            if lock is not None:
                lock.release()

    def _update_pipeline_body(self):
        self._set_global_status("Updating data…")
        self._ui_call(lambda:self._refresh_update_status("UPDATING",None))
        try:
            report=self.updater.update_all()
            # Judge every pending freeze against any draw now in DB.
            for key in GAMES:
                draws=self.db.draws(key,era_only=True,model_ready=True)
                for d in draws[-30:]:
                    self.learning.judge_new_draw(key,d)
                # V1.2.4: enrich already-judged V1.2.3 freezes with Champion Match
                # diagnostics. This is read-only against the frozen prediction and lets
                # tonight's result be learned immediately after upgrading.
                self.learning.backfill_champion_diagnostics(key, draws, limit=250)
                # Shadow neural models retrain only when a new verified/history draw extends the cutoff.
                if self.nn[key].needs_retrain(draws):
                    self.nn[key].train(draws)
                if self.region_nn[key].needs_retrain(draws):
                    self.region_nn[key].train(draws)
                # One-time V1.1 upgrade bridge: if a V1.0.x Production prediction is still
                # safely pre-draw, attach the new shadow suite without changing Production.
                target, valid = self._prediction_target(key, draws)
                strategy_backfill_blocked = bool(
                    target and self.db.get_state(f"strategy_shadow_backfill_blocked_{key}_{target}", False)
                )
                needs_v14_strategy = bool(target) and not strategy_backfill_blocked and any(
                    not self.db.freeze_by_prefix(key,target,prefix)
                    for prefix in V14_STRATEGY_PREFIXES.values())
                needs_budget = bool(target) and not self.db.portfolio_decision(key,target,PORTFOLIO_POLICY_VERSION)
                if (valid and target and self.db.official_freeze(key,target)
                        and (not self.db.random_freeze(key,target) or not self.db.research_freeze(key,target)
                             or needs_v14_strategy or needs_budget)):
                    self._freeze_research_suite(key, quiet=True)
                else:
                    self.refresh_game_state(key)
            self._set_global_status("Ready")
            self._ui_call(lambda:self._refresh_update_status(report.get("status","—"),report.get("finished_at")))
        except Exception:
            self._ui_call(lambda:self._refresh_update_status("FAILED",None))
            raise

    def _set_global_status(self,text):
        for key in GAMES:
            self.game_state[key]["status"]=text
            self._ui_call(self.cards[key].refresh)

    def _prediction_target(self, key, draws):
        if not draws:
            return None, False
        target = next_draw_date(key, date.fromisoformat(draws[-1]["draw_date"]))
        # BC draw-cycle guard: a missing result must never unlock a prediction for a draw
        # already in the past. On the scheduled draw date generation is allowed only
        # before 19:30 Pacific; after that the app requires a data update first.
        now = pacific_now()
        today = now.date()
        valid = target > today or (target == today and (now.hour, now.minute) < (PREDICTION_CUTOFF_HOUR, PREDICTION_CUTOFF_MINUTE))
        return target.isoformat(), valid

    def _performance(self, key):
        from statistics import mean
        cfg=GAMES[key]
        expected=cfg.pick*cfg.pick/cfg.max_number
        out={"random":round(expected,4),"n":0,"rnd_n":0,"res_n":0}
        pairs=self.db.paired_model_performance(key,200)
        if pairs:
            diffs=[c-p for _,p,c,_ in pairs]
            z=paired_z_score(diffs)
            out.update({
                "n":len(pairs),"pavg":round(mean(p for _,p,_,_ in pairs),4),
                "cavg":round(mean(c for _,_,c,_ in pairs),4),
                "edge":round(mean(diffs),4),"z":round(z,3),
                "gate":"ELIGIBLE" if len(pairs)>=100 and mean(diffs)>.015 and z>=paired_t_critical_95(len(diffs)) else "NOT READY"
            })
        rpairs=self.db.paired_shadow_performance(key,"RND",200)
        if rpairs:
            # V1.6.1: Random Control is retained only as a descriptive structure-control
            # diagnostic. Its deliberate diversification changes the null distribution,
            # so P-vs-RND is never promotion evidence. Strategy skill is evaluated
            # against each portfolio's own fair-lottery self-null instead.
            rd=[p-r for _,p,r,_,_ in rpairs]
            rz=paired_z_score(rd)
            out.update({
                "rnd_n":len(rpairs),
                "rnd_avg":round(mean(r for _,_,r,_,_ in rpairs),4),
                "prod_vs_rnd":round(mean(rd),4),"rnd_z":round(rz,3),
                "rnd_gate":"LEGACY STRUCTURE CONTROL — NOT PROMOTION EVIDENCE",
                "rnd_confirmed":False,
            })
        respairs=self.db.paired_shadow_performance(key,"RES",200)
        if respairs:
            diffs=[r-p for _,p,r,_,_ in respairs]
            rz=paired_z_score(diffs)
            res_screen = len(respairs)>=100 and mean(diffs)>.015 and rz>=paired_t_critical_95(len(diffs))
            res_confirm = len(respairs)>=200 and mean(diffs)>.015 and rz>=2.58
            out.update({
                "res_n":len(respairs),
                "res_avg":round(mean(r for _,_,r,_,_ in respairs),4),
                "res_vs_prod":round(mean(diffs),4),"res_z":round(rz,3),
                "res_gate":"CONFIRMATION SIGNAL" if res_confirm else ("SCREENING SIGNAL" if res_screen else "NOT READY"),
                "res_confirmed":bool(res_confirm),
            })
        return out

    def _main_bonus_audit(self, key, limit=80):
        checked_freezes=0
        checked_bindings=0
        errors=[]
        warnings=[]
        legacy_freezes=0
        legacy_partial_freezes=0
        nonlegacy_partial_freezes=0
        missing_total=0
        for f in self.db.recent_freezes(key,limit=limit):
            version=str(f.get("model_version") or "")
            if not (version.startswith("P") or version.startswith("C")):
                continue
            try:
                preds=json.loads(f.get("predictions_json") or "[]")
                raw=json.loads(f.get("bonus_rank_json") or "[]")
            except Exception:
                continue
            if not preds or not raw:
                continue
            rep=main_bonus_consistency(
                preds,raw,max_number=GAMES[key].max_number,expected_limit=10)
            checked_freezes += 1
            checked_bindings += int(rep.get("checked_bindings",0))
            is_legacy=bool(rep.get("legacy"))
            legacy_freezes += 1 if is_legacy else 0
            missing_total += len(rep.get("missing_bindings") or [])
            if rep.get("status") == "PARTIAL":
                if is_legacy:
                    legacy_partial_freezes += 1
                else:
                    nonlegacy_partial_freezes += 1
            if rep.get("errors"):
                errors.extend({"target":f.get("target_draw_date"),"model":version,**e} for e in rep.get("errors"))
            if rep.get("warnings"):
                warnings.extend({"target":f.get("target_draw_date"),"model":version,**w} for w in rep.get("warnings"))
        if errors or nonlegacy_partial_freezes:
            status="FAIL"
        elif legacy_partial_freezes:
            status="LEGACY PARTIAL"
        else:
            status="PASS"
        return {
            "status":status,"checked_freezes":checked_freezes,"checked_bindings":checked_bindings,
            "errors":errors,"warnings":warnings,"legacy_freezes":legacy_freezes,
            "partial_freezes":legacy_partial_freezes+nonlegacy_partial_freezes,
            "legacy_partial_freezes":legacy_partial_freezes,
            "nonlegacy_partial_freezes":nonlegacy_partial_freezes,
            "missing_bindings":missing_total,
        }

    def refresh_game_state(self,key):
        draws=self.db.draws(key,era_only=True,model_ready=True)
        if len(draws)<1:
            return
        all_draws=self.db.draws(key,era_only=False,model_ready=True)
        cfg=GAMES[key]
        pweights_raw,pver=self.db.active_weights(key,"production",cfg.default_weights)
        cweights_raw,cver=self.db.active_weights(key,"challenger",cfg.default_weights)
        pweights=normalize_main_weights(pweights_raw)
        cweights=normalize_main_weights(cweights_raw)
        bpweights,bpver=self.db.active_weights(key,"bonus_production",BONUS_WEIGHTS)
        bcweights,bcver=self.db.active_weights(key,"bonus_challenger",BONUS_WEIGHTS)
        target, target_valid=self._prediction_target(key,draws)
        frozen=self.db.official_freeze(key,target) if target else None
        rnd_frozen=self.db.random_freeze(key,target) if target else None
        res_frozen=self.db.research_freeze(key,target) if target else None
        strategy_freezes=self.db.strategy_freezes(key,target,V14_STRATEGY_PREFIXES) if target else {}
        validation_summary=strategy_validation_summary(self.db,key,limit=250)
        freeze_integrity=verify_freeze_integrity(frozen) if frozen else {"status":"NO_FREEZE","ok":False}
        preds=[]; raw_bonus=[]; research_preds=[]; frozen_ctx={}
        created=None
        if frozen:
            try: preds=json.loads(frozen.get("predictions_json") or "[]")
            except Exception: preds=[]
            try: raw_bonus=json.loads(frozen.get("bonus_rank_json") or "[]")
            except Exception: raw_bonus=[]
            try: frozen_ctx=json.loads(frozen.get("factor_context_json") or "{}")
            except Exception: frozen_ctx={}
            created=frozen.get("created_at")
        if res_frozen:
            try: research_preds=json.loads(res_frozen.get("predictions_json") or "[]")
            except Exception: research_preds=[]
        prod=PredictionEngine(key,draws,pweights,seed=20260912)
        # V1.1.1 integrity rule: an official freeze is immutable. Legacy Pick-#1-only
        # Bonus payloads are NOT silently enriched with current/later data for display.
        bonus_payload=normalize_bonus_payload(raw_bonus,preds)
        bonus_binding_mode="NONE"
        if preds:
            current_consistency=main_bonus_consistency(
                preds, bonus_payload, max_number=cfg.max_number, expected_limit=10)
            if current_consistency.get("status") == "FAIL":
                bonus_binding_mode="FROZEN CONSISTENCY ERROR"
            elif bonus_payload.get("legacy"):
                bonus_binding_mode="LEGACY FROZEN · PICK #1 ONLY"
            elif current_consistency.get("status") == "PARTIAL":
                bonus_binding_mode="PARTIAL FROZEN BINDING"
            else:
                bonus_binding_mode="V1.1 FROZEN PER-MAIN"
        else:
            current_consistency={"status":"—","errors":[],"warnings":[],"bound_main_picks":0,"total_main_picks":0,"missing_bindings":[]}
        champion_records=self.db.champion_learning_records(key,prefix="P",limit=200)
        champion_summary=summarize_champion_records(champion_records)
        champion_shadow_weights={}; champion_shadow_version="—"
        if champion_summary.get("n"):
            cs_raw,champion_shadow_version=self.db.active_weights(key,"champion_shadow",pweights)
            champion_shadow_weights=normalize_main_weights(cs_raw)
        jackpot=self.db.latest_jackpot_snapshot(key) or {}
        jackpot_refresh=self.db.get_state(f"jackpot_refresh_{key}",{}) or {}
        if jackpot and str(jackpot_refresh.get("status") or "CURRENT").upper() in {"STALE","FAILED"}:
            jackpot=dict(jackpot)
            jackpot["status"]="STALE"
            jackpot["refresh_error"]=jackpot_refresh.get("error")
            jackpot["last_refresh_attempt"]=jackpot_refresh.get("checked_at")
        jackpot_econ=self.db.get_state(f"jackpot_economics_{key}",{}) or jackpot_economics(key,jackpot)
        jackpot_history=self.db.jackpot_history(key,limit=100)
        portfolio_row=self.db.portfolio_decision(key,target,PORTFOLIO_POLICY_VERSION) if target else None
        portfolio_decision=(portfolio_row or {}).get("decision") or {}
        portfolio_records=self.db.portfolio_learning_records(key,limit=250)
        portfolio_learning=learn_shadow_policy(portfolio_records)
        portfolio_validation=portfolio_validation_summary(portfolio_records)
        portfolio_line_learning=line_selection_learning(portfolio_records)
        budget_learning=budget_frontier_learning(portfolio_records,key)
        historical_bayes_observations=self.db.get_state(f"bayesian_history_observations_{key}",[]) or []
        forward_bayes_observations=forward_strategy_observations(self.db,key)
        bayesian_strategy=hierarchical_strategy_posterior(
            historical_bayes_observations + forward_bayes_observations,key)
        state=self.game_state[key]
        state.update({
            "latest":self.db.latest_draw(key),"count":self.db.count_draws(key),"history_health":self.updater.history_health(key),"preds":preds,
            "bonus_payload":bonus_payload,"bonus_binding_mode":bonus_binding_mode,
            "main_bonus_consistency":current_consistency,"main_bonus_audit":self._main_bonus_audit(key),
            "region":prod.region_summary(),"regime":regime_summary(key,all_draws,draws),
            "pweights":pweights,"cweights":cweights,"pver":pver,"cver":cver,
            "bpweights":bpweights,"bcweights":bcweights,"bpver":bpver,"bcver":bcver,
            "nn_status":self.nn[key].status,"region_nn_status":self.region_nn[key].status,
            "region_nn_prediction":self.region_nn[key].predict(draws),
            "learning":self.db.latest_learning(key,"challenger"),"performance":self._performance(key),
            "champion_summary":champion_summary,"champion_shadow_weights":champion_shadow_weights,
            "champion_shadow_version":champion_shadow_version,
            "champion_latest":(champion_records[0] if champion_records else None),
            "target":target,"prediction_frozen":bool(frozen),"prediction_created":created,
            "random_status": RANDOM_CONTROL_VERSION+" FROZEN" if rnd_frozen else "WAITING",
            "research_status": RESEARCH_PORTFOLIO_VERSION+" FROZEN" if res_frozen else "WAITING",
            "v14_strategy_status":{mode:("FROZEN" if strategy_freezes.get(mode) else "WAITING") for mode in V14_STRATEGY_PREFIXES},
            "v14_validation":validation_summary,"freeze_integrity":freeze_integrity,
            "jackpot":jackpot,"jackpot_economics":jackpot_econ,"jackpot_history":jackpot_history,"jackpot_refresh":jackpot_refresh,
            "portfolio_decision":portfolio_decision,"portfolio_learning_status":portfolio_learning,
            "portfolio_validation":portfolio_validation,"portfolio_line_learning":portfolio_line_learning,"budget_learning":budget_learning,
            "bayesian_strategy":bayesian_strategy,
            "research_preds": research_preds,
            "research_portfolio_summary": portfolio_summary(research_preds,key) if research_preds else {},
            "coverage_summary": coverage_summary(preds,key) if preds else {},
            "coverage_matrix": overlap_matrix(preds,limit=12) if preds else [],
            "candidate_number_profile":frozen_ctx.get("candidate_number_profile") or [],
            "current_draw": build_current_draw_snapshot(self.db, key),
            "can_generate":bool(target_valid and not frozen),"status":"Ready"
        })
        self._ui_call(self.cards[key].refresh)

    def generate_official_async(self,key):
        self._start_worker(lambda:self.generate_official_prediction(key))

    def generate_official_prediction(self,key):
        draws=self.db.draws(key,era_only=True,model_ready=True)
        if len(draws)<3:
            raise RuntimeError("Not enough draw data to generate an official prediction.")
        target, valid=self._prediction_target(key,draws)
        if not target or not valid:
            raise RuntimeError("Latest draw data is stale. Update data before generating the next prediction.")
        if self.db.official_freeze(key,target):
            self.refresh_game_state(key)
            return
        cfg=GAMES[key]
        pweights_raw,pver=self.db.active_weights(key,"production",cfg.default_weights)
        cweights_raw,cver=self.db.active_weights(key,"challenger",cfg.default_weights)
        pweights=normalize_main_weights(pweights_raw)
        cweights=normalize_main_weights(cweights_raw)
        bpweights,bpver=self.db.active_weights(key,"bonus_production",BONUS_WEIGHTS)
        bcweights,bcver=self.db.active_weights(key,"bonus_challenger",BONUS_WEIGHTS)
        nn_scores=self.nn[key].predict_scores(draws)
        # Fixed seed + fixed algorithm/data cutoff => reproducible official result.
        seed=int(draws[-1]["draw_date"].replace("-", "")) + (649 if key=="649" else 52)
        prod=PredictionEngine(key,draws,pweights,seed=seed)
        chall=PredictionEngine(key,draws,cweights,seed=seed)
        # V1.4: calculate Production candidates once, then derive Balanced/Score-only/
        # Focused/Pure-Coverage from the exact same pre-draw opportunity set. This
        # isolates portfolio construction from number/combo scoring in later diagnosis.
        prod_suite=prod.generate_strategy_suite(
            candidate_count=DEFAULT_CANDIDATES,top_n=20,neural_scores=nn_scores,
            modes=("balanced","score_only","focused","pure_coverage","concentrated"))
        pp=prod_suite["portfolios"]["balanced"]
        # Challenger receives the exact same search budget and RNG seed. Generate a
        # suite so we can also prove the raw candidate universe is identical even
        # though model scores/order may differ.
        chall_suite=chall.generate_strategy_suite(
            candidate_count=DEFAULT_CANDIDATES,top_n=20,neural_scores=nn_scores,
            modes=("balanced",))
        cp=chall_suite["portfolios"]["balanced"]
        candidate_universe_equal=(
            prod_suite.get("candidate_universe_hash")
            == chall_suite.get("candidate_universe_hash")
        )
        if not candidate_universe_equal:
            raise RuntimeError("Production/Challenger candidate-universe integrity gate failed.")
        # V1.1: Bonus is conditional on each Main combination, not only Pick #1.
        # The Bonus submodel is kept completely separate from Main Combination ranking.
        pb=build_bonus_payload(pp,lambda main,lim: prod.bonus_rank(main,lim,weights=bpweights),limit=10)
        cb=build_bonus_payload(cp,lambda main,lim: chall.bonus_rank(main,lim,weights=bcweights),limit=10)
        # Defensive consistency gate: a bound Bonus must never appear in its Main combination.
        pcheck=main_bonus_consistency(pp,pb,max_number=cfg.max_number,expected_limit=10)
        ccheck=main_bonus_consistency(cp,cb,max_number=cfg.max_number,expected_limit=10)
        if pcheck.get("status") != "PASS" or ccheck.get("status") != "PASS":
            raise RuntimeError("Main-Bonus consistency gate failed; prediction was not frozen.")
        cutoff=draws[-1]["draw_date"]
        prediction_run_id=sha256_json({
            "game":key,"target":target,"cutoff":cutoff,"app_version":APP_VERSION,
            "seed":seed,"candidate_universe_hash":prod_suite.get("candidate_universe_hash"),
        })[:24]
        p_integrity=build_freeze_integrity(
            predictions=pp,weights=pweights,game=key,target=target,cutoff=cutoff,
            app_version=APP_VERSION,model_version=pver,coverage_mode="balanced",
            coverage_engine=next((r.get("coverage_engine") for r in pp if r.get("coverage_engine")),None),
            candidate_hash=prod_suite.get("candidate_pool_hash"))
        c_integrity=build_freeze_integrity(
            predictions=cp,weights=cweights,game=key,target=target,cutoff=cutoff,
            app_version=APP_VERSION,model_version=cver,coverage_mode="balanced",
            coverage_engine=next((r.get("coverage_engine") for r in cp if r.get("coverage_engine")),None),
            candidate_hash=chall_suite.get("candidate_pool_hash"))
        frozen_target=self.learning.freeze_next(
            key,draws,pp,cp,pver,cver,pb,cb,
            production_bonus_version=bpver, challenger_bonus_version=bcver, app_version=APP_VERSION,
            production_context_extra={
                "integrity":p_integrity,"pipeline_architecture":"V1.5 staged evaluation + adaptive portfolio",
                "candidate_pool_shared_with_strategy_shadows":True,
                "candidate_count":DEFAULT_CANDIDATES,
                "search_budget_equal_to_challenger":True,
                "seed_shared_with_challenger":True,
                "candidate_number_profile":prod_suite.get("candidate_number_profile") or [],
                "candidate_number_profile_schema":"CANDNUM1.0",
                "candidate_universe_hash":prod_suite.get("candidate_universe_hash"),
                "candidate_universe_equal_to_challenger":candidate_universe_equal,
                "prediction_run_id":prediction_run_id,
            },
            challenger_context_extra={
                "integrity":c_integrity,
                "candidate_count":DEFAULT_CANDIDATES,
                "search_budget_equal_to_production":True,
                "seed_shared_with_production":True,
                "candidate_universe_hash":chall_suite.get("candidate_universe_hash"),
                "candidate_universe_equal_to_production":candidate_universe_equal,
                "prediction_run_id":prediction_run_id,
            })
        self._freeze_v14_strategy_portfolios(
            key,frozen_target,cutoff,pweights,prod_suite,same_candidate_pool_with_production=True,
            prediction_run_id=prediction_run_id)
        self._freeze_v15_budget_portfolio(key,frozen_target,pp,prediction_run_id=prediction_run_id)
        self.db.set_state(f"official_prediction_{key}_{frozen_target}",{
            "created_at":datetime.now().isoformat(timespec="seconds"),
            "data_cutoff":draws[-1]["draw_date"],"production_version":pver,
            "algorithm_version":APP_VERSION,"prediction_run_id":prediction_run_id
        })
        # V1.1 shadow suite is frozen separately; it cannot alter Production.
        self._freeze_research_suite(key, quiet=True)
        self.refresh_game_state(key)

    def _freeze_v15_budget_portfolio(self,key,target,preds,prediction_run_id=None):
        """Freeze complete Top-20 subset frontiers before the draw.

        Because every line-count frontier is frozen now, a user can later type any
        dollar budget without recomputing against post-draw information.
        """
        if not target or not preds:
            return None
        existing=self.db.portfolio_decision(key,target,PORTFOLIO_POLICY_VERSION)
        if existing:
            return existing
        records=self.db.portfolio_learning_records(key,limit=250)
        learned=learn_shadow_policy(records)
        budget_learned=budget_frontier_learning(records,key)
        line_learned=line_selection_learning(records)
        prod_frontier=PortfolioOptimizer(key).frontier(preds,max_lines=min(20,len(preds)))
        shadow_frontier=PortfolioOptimizer(key,learned.get("weights")).frontier(preds,max_lines=min(20,len(preds)))
        jackpot=self.db.latest_jackpot_snapshot(key) or {}
        economics=self.db.get_state(f"jackpot_economics_{key}",{}) or jackpot_economics(key,jackpot)
        frozen_rows=[]
        for i,r in enumerate(preds):
            frozen_rows.append({
                "rank":int(r.get("rank",i+1)),
                "numbers":[int(n) for n in (r.get("numbers") or [])],
                "score":float(r.get("score",0.0)),
                "components":dict(r.get("components") or {}),
                "crowd_risk":r.get("crowd_risk"),
            })
        views={}
        deployment_views={}
        budget_opt=PortfolioOptimizer(key)
        for b in PORTFOLIO_DEFAULT_BUDGETS:
            views[str(int(b))]=budget_opt.for_budget(prod_frontier,b,allow_unspent=True)
            deployment_views[str(int(b))]={
                "efficiency": budget_opt.for_budget(prod_frontier,b,allow_unspent=True),
                "max_deployment": budget_opt.for_budget(prod_frontier,b,allow_unspent=False),
            }
        decision={
            "schema":"BUDGET_PORTFOLIO1.3",
            "game":key,"target_draw_date":str(target),"model_version":PORTFOLIO_POLICY_VERSION,
            "prediction_run_id":prediction_run_id,
            "frozen_rows":frozen_rows,
            "production_frontier":prod_frontier,
            "shadow_frontier":shadow_frontier,
            "standard_budget_views":views,
            "deployment_views":deployment_views,
            "learning_state_at_freeze":learned,
            "budget_learning_at_freeze":budget_learned,
            "line_learning_state_at_freeze":line_learned,
            "jackpot_snapshot":jackpot,
            "jackpot_economics":economics,
            "production_impact_of_shadow":0.0,
            "hard_rules":{
                "user_budget_is_ceiling":True,
                "loss_chasing":False,
                "martingale":False,
                "recombine_numbers":False,
                "zero_bet_allowed":True,
                "effective_sample_unit":"draw",
            },
            "note":"Budget AI selects only from immutable frozen Top-20; complete line-count frontier is frozen pre-draw.",
        }
        return self.db.save_portfolio_decision(key,target,PORTFOLIO_POLICY_VERSION,decision)

    def _freeze_v14_strategy_portfolios(self,key,target,cutoff,weights,suite,
                                         same_candidate_pool_with_production=False,
                                         prediction_run_id=None):
        """Freeze same-budget portfolio strategies without changing Production."""
        created=[]
        portfolios=(suite or {}).get("portfolios") or {}
        candidate_hash=(suite or {}).get("candidate_pool_hash")
        for mode,version in V14_STRATEGY_VERSIONS.items():
            prefix=V14_STRATEGY_PREFIXES[mode]
            if self.db.freeze_by_prefix(key,target,prefix):
                continue
            preds=portfolios.get(mode) or []
            if not preds:
                continue
            cov_engine=next((r.get("coverage_engine") for r in preds if r.get("coverage_engine")),None)
            integrity=build_freeze_integrity(
                predictions=preds,weights=weights,game=key,target=target,cutoff=cutoff,
                app_version=APP_VERSION,model_version=version,coverage_mode=mode,
                coverage_engine=cov_engine,candidate_hash=candidate_hash)
            self.db.save_freeze(
                key,target,version,cutoff,preds,[],
                {
                    "role":"v14_strategy_shadow","shadow_only":True,"strategy":mode,
                    "same_budget_lines":len(preds),
                    "same_candidate_pool_with_production":bool(same_candidate_pool_with_production),
                    "candidate_pool_hash":candidate_hash,
                    "candidate_number_profile":(suite or {}).get("candidate_number_profile") or [],
                    "candidate_number_profile_schema":"CANDNUM1.0",
                    "prediction_run_id":prediction_run_id,
                    "coverage_mode":mode,"coverage_engine":cov_engine,
                    "integrity":integrity,
                    "note":"V1.4 frozen strategy comparator. It cannot alter Production or auto-promote.",
                })
            created.append(version)
        return created

    def freeze_research_async(self,key):
        self.game_state[key]["status"]="Freezing V1.4 validation suite…"
        self._ui_call(self.cards[key].refresh)
        self._start_worker(lambda:self._freeze_research_suite(key, quiet=False))

    def _freeze_research_suite(self,key,quiet=False):
        draws=self.db.draws(key,era_only=True,model_ready=True)
        all_draws=self.db.draws(key,era_only=False,model_ready=True)
        if len(draws)<3:
            raise RuntimeError("Not enough audited draw data for the V1.4 Model Validation Lab.")
        target, valid=self._prediction_target(key,draws)
        if not target or not valid:
            raise RuntimeError("The next target is not safely pre-draw. Update data first.")
        prod_freeze=self.db.official_freeze(key,target)
        if not prod_freeze:
            raise RuntimeError("Generate/freeze the official Production prediction first; Research shadows must share the same target and cutoff.")
        cutoff=str(prod_freeze.get("data_cutoff") or draws[-1]["draw_date"])
        try:
            prod_preds=json.loads(prod_freeze.get("predictions_json") or "[]")
        except Exception:
            prod_preds=[]
        if prod_preds:
            self._freeze_v15_budget_portfolio(key,target,prod_preds)
        created=[]
        weights_raw,_=self.db.active_weights(key,"production",GAMES[key].default_weights)
        weights=normalize_main_weights(weights_raw)
        missing_strategy=any(
            not self.db.freeze_by_prefix(key,target,prefix)
            for prefix in V14_STRATEGY_PREFIXES.values())
        if missing_strategy:
            # Integrity rule: never fabricate a supposedly comparable strategy shadow
            # later from a newly generated candidate universe. If the exact original
            # Production opportunity set was not frozen, the comparator stays missing.
            self.db.set_state(f"strategy_shadow_backfill_blocked_{key}_{target}",{
                "status":"SKIPPED_NO_ORIGINAL_CANDIDATE_UNIVERSE",
                "at":datetime.now().isoformat(timespec="seconds"),
                "reason":"V1.6.1 refuses post-hoc regeneration of missing strategy shadows from a different candidate pool.",
            })
        if not self.db.random_freeze(key,target):
            rnd=RandomControlEngine(key,stable_seed(key,target,"RND1.0")).generate(
                top_n=RESEARCH_PORTFOLIO_SIZE,candidate_count=1800)
            rnd_integrity=build_freeze_integrity(
                predictions=rnd,weights={},game=key,target=target,cutoff=cutoff,
                app_version=APP_VERSION,model_version=RANDOM_CONTROL_VERSION,
                coverage_mode="random_control",coverage_engine=None,candidate_hash=None)
            self.db.save_freeze(
                key,target,RANDOM_CONTROL_VERSION,cutoff,rnd,[],
                {"role":"random_control","shadow_only":True,"integrity":rnd_integrity,
                 "note":"No historical signal; uniform random candidate pool with diversity matching for portfolio comparison."}
            )
            created.append(RANDOM_CONTROL_VERSION)
        if not self.db.research_freeze(key,target):
            candidate_engine=PredictionEngine(key,draws,weights,seed=stable_seed(key,target,RESEARCH_PORTFOLIO_VERSION+"-candidates"))
            candidates=candidate_engine.scored_candidates(candidate_count=3500,limit=100,neural_scores=None)
            res=ResearchPortfolioOptimizer(key,all_draws).optimize(candidates,top_n=RESEARCH_PORTFOLIO_SIZE)
            res_integrity=build_freeze_integrity(
                predictions=res,weights=weights,game=key,target=target,cutoff=cutoff,
                app_version=APP_VERSION,model_version=RESEARCH_PORTFOLIO_VERSION,
                coverage_mode="research_portfolio",coverage_engine=None,candidate_hash=None)
            self.db.save_freeze(
                key,target,RESEARCH_PORTFOLIO_VERSION,cutoff,res,[],
                {"role":"research_portfolio","shadow_only":True,"integrity":res_integrity,
                 "weights":{"model_score":0.90,"crowd_avoidance":0.00,"regime_normalized":0.10},
                 "note":"Research-only portfolio. Sharing-risk/crowd proxy is advisory only (0% rank weight); regime deviations are descriptive, not proven predictive signals."}
            )
            created.append(RESEARCH_PORTFOLIO_VERSION)
        self.db.set_state(f"research_v14_{key}_{target}",{
            "target":target,"data_cutoff":cutoff,"created":created or ["already_frozen"],
            "version":APP_VERSION,"shadow_only":True
        })
        self.refresh_game_state(key)
        self.game_state[key]["status"]="Ready"
        if not quiet:
            msg=("V1.4 Validation Suite frozen for " + target + ".\n\n"
                 + ("Created: " + ", ".join(created) if created else "Validation shadows were already frozen.")
                 + "\nProduction prediction was not changed.")
            self._ui_call(lambda:(self.cards[key].refresh(),self.cards[key].show_analysis("research"),messagebox.showinfo("V1.4 Model Validation Lab",msg)))

    def run_research_async(self,key):
        self.game_state[key]["status"]="Research tests running…"
        self._ui_call(self.cards[key].refresh)
        self._start_worker(lambda:self._run_research(key))

    def _run_research(self,key):
        draws=self.db.draws(key,era_only=True,model_ready=True)
        weights_raw,_=self.db.active_weights(key,"production",GAMES[key].default_weights)
        weights=normalize_main_weights(weights_raw)
        bayes_eval_draws=min(30,max(1,len(draws)-30))
        bayes_walk=bayesian_strategy_walk_forward(
            key,draws,weights,eval_draws=bayes_eval_draws,candidate_count=520,
            line_counts=(3,5,8,10,20))
        historical_observations=(bayes_walk.get("observations") or []) if bayes_walk.get("status") == "ok" else []
        self.db.set_state(f"bayesian_history_observations_{key}",historical_observations)
        forward_observations=forward_strategy_observations(self.db,key)
        bayesian_strategy=hierarchical_strategy_posterior(
            historical_observations + forward_observations,key)
        self.db.set_state(f"bayesian_strategy_{key}",bayesian_strategy)
        bayes_walk_compact=dict(bayes_walk)
        bayes_walk_compact.pop("observations",None)
        result={
            "walk_forward":walk_forward_test(key,draws,weights,eval_draws=20,candidate_count=900,top_n=8),
            "random_control":random_control_walk_forward(key,draws,weights,eval_draws=16,candidate_count=700,top_n=8),
            "shuffle":shuffle_test(key,draws,weights,repeats=4,eval_draws=8,candidate_count=450),
            "synthetic_null":null_synthetic_test(key,draws,weights,repeats=3,eval_draws=8,candidate_count=400),
            "feature_ablation":feature_ablation_test(key,draws,weights,eval_draws=6,candidate_count=420,top_n=8),
            "rank_stability":rank_stability_test(key,draws,weights,transitions=5,candidate_count=500,top_n=10),
            "coverage_strategy":coverage_strategy_backtest(key,draws,weights,eval_draws=6,candidate_count=520,top_n=8),
            "bayesian_walk_forward":bayes_walk_compact,
        }
        # Strip long per-draw rows from UI result.
        result["walk_forward"].pop("rows",None)
        if isinstance(result.get("rank_stability"), dict):
            result["rank_stability"].pop("rows", None)
        if isinstance(result.get("coverage_strategy"), dict):
            result["coverage_strategy"].pop("rows", None)
        self.game_state[key]["research"]=result
        self.game_state[key]["bayesian_strategy"]=bayesian_strategy
        self.game_state[key]["status"]="Ready"
        self._ui_call(lambda:(self.cards[key].refresh(),self.cards[key].show_analysis("research")))

    def repair_history_async(self,key):
        self.game_state[key]["status"]="Repairing historical database…"
        self._ui_call(self.cards[key].refresh)
        self._start_worker(lambda:self._repair_history(key))

    def _repair_history(self,key):
        result=self.updater.repair_history(key,force_full=True)
        self.refresh_game_state(key)
        self.game_state[key]["status"]="Ready"
        self._ui_call(lambda:(self.cards[key].refresh(),self.cards[key].show_analysis("data")))
        self._ui_call(lambda:messagebox.showinfo("History Repair",result.get("message","History repair completed")))

    def audit_history_async(self,key):
        self.game_state[key]["status"]="Running integrity audit…"
        self._ui_call(self.cards[key].refresh)
        self._start_worker(lambda:self._audit_history(key))

    def _audit_history(self,key):
        health=self.updater.audit_history(key)
        self.refresh_game_state(key)
        self.game_state[key]["status"]="Ready"
        mba=self._main_bonus_audit(key)
        msg=(f"Raw audit {health.get('status')}: coverage {health.get('coverage_pct')}%, "
             f"raw integrity {health.get('integrity_score')}%, model integrity {health.get('usable_integrity_score')}% "
             f"[{health.get('model_data_status')}]; missing {health.get('missing')}, "
             f"unexpected {health.get('unexpected')}, invalid {health.get('invalid')}, "
             f"conflicts {health.get('conflicts')}, quarantined {len(health.get('model_exclusions',[]) or [])}.\n\n"
             f"Main-Bonus consistency / 主号-特别号一致性: {mba.get('status')} · "
             f"checked freezes {mba.get('checked_freezes',0)} · errors {len(mba.get('errors') or [])}.")
        self._ui_call(lambda:(self.cards[key].refresh(),self.cards[key].show_analysis("data"),messagebox.showinfo("Integrity Audit",msg)))

    def import_history_csv(self,key):
        path=filedialog.askopenfilename(title=f"Import {GAMES[key].name} history CSV",filetypes=[("CSV files","*.csv"),("All files","*.*")])
        if not path:
            return
        self._start_worker(lambda:self._import_history_csv_worker(key,path))

    def _import_history_csv_worker(self,key,path):
        result=self.updater.import_history_csv(key,path)
        self.refresh_game_state(key)
        self._ui_call(lambda:(self.cards[key].show_analysis("data"),messagebox.showinfo("CSV Import",result.get("message","Import completed"))))

    def periodic_update(self):
        # Check every 30 minutes, but only call remote sources when a scheduled draw is missing.
        if any(self.updater.needs_poll(k) for k in GAMES):
            self._start_worker(self.update_pipeline)
        self.after(30*60*1000,self.periodic_update)


if __name__=="__main__":
    app=LotteryApp()
    app.mainloop()
