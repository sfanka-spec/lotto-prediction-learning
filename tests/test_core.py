import tempfile
import unittest
from pathlib import Path

from lottery_ai.analysis import exact_sum_distribution
from lottery_ai.config import GAMES
from lottery_ai.engine import PredictionEngine
from lottery_ai.providers import validate_draw, WCLCOfficialProvider


class FakeResponse:
    status_code = 200
    def __init__(self, text): self.text=text


class CoreTests(unittest.TestCase):
    def test_exact_combination_totals(self):
        self.assertEqual(sum(exact_sum_distribution(49,6).values()), 13_983_816)
        self.assertEqual(sum(exact_sum_distribution(52,7).values()), 133_784_560)

    def test_draw_validation(self):
        self.assertTrue(validate_draw("649", [1,2,3,4,5,49], 6))
        self.assertFalse(validate_draw("649", [1,2,3,4,5,50], 6))
        self.assertFalse(validate_draw("649", [1,2,3,4,5,5], 6))
        self.assertFalse(validate_draw("max", [1,2,3,4,5,6,7], 7))

    def test_official_parser_max(self):
        html='''<html><h4>Friday, September 11, 2026</h4>
        <ul><li>1</li><li>38</li><li>41</li><li>44</li><li>45</li><li>49</li><li>51</li><li>Bonus 47</li></ul></html>'''
        p=WCLCOfficialProvider()
        p.session.get=lambda *a,**k: FakeResponse(html)
        d=p.latest("max")
        self.assertEqual(d["date"],"2026-09-11")
        self.assertEqual(d["numbers"],[1,38,41,44,45,49,51])
        self.assertEqual(d["bonus"],47)

    def test_official_parser_649(self):
        html='''<html><h4>Wednesday, September 09, 2026</h4><div>CLASSIC DRAW</div>
        <ul><li>14</li><li>18</li><li>27</li><li>35</li><li>41</li><li>47</li><li>Bonus 17</li></ul></html>'''
        p=WCLCOfficialProvider()
        p.session.get=lambda *a,**k: FakeResponse(html)
        d=p.latest("649")
        self.assertEqual(d["numbers"],[14,18,27,35,41,47])
        self.assertEqual(d["bonus"],17)

    def test_prediction_engine(self):
        draws=[]
        for i in range(1,31):
            nums=sorted({((i+j*7)%49)+1 for j in range(6)})
            while len(nums)<6:
                nums.append(max(nums)+1)
            nums=sorted(nums[:6])
            bonus=next(n for n in range(1,50) if n not in nums)
            draws.append({"draw_date":f"2026-01-{(i-1)%28+1:02d}","numbers":nums,"bonus":bonus})
        e=PredictionEngine("649",draws,GAMES["649"].default_weights,seed=7)
        rows=e.generate(candidate_count=300,top_n=5)
        self.assertEqual(len(rows),5)
        self.assertTrue(all(len(r["numbers"])==6 for r in rows))
        self.assertTrue(all(0<=r["score"]<=100 for r in rows))


if __name__ == "__main__":
    unittest.main()

def test_official_freeze_is_persistent_and_unique(tmp_path):
    from lottery_ai.db import Database
    db = Database(tmp_path / "lottery.db")
    pred = [{"numbers":[1,2,3,4,5,6],"score":80.0,"components":{}}]
    db.save_freeze("649", "2026-09-16", "P1.0", "2026-09-12", pred, [[7,70.0]], {})
    db.save_freeze("649", "2026-09-16", "P1.0", "2026-09-12", pred, [[8,71.0]], {})
    f = db.official_freeze("649", "2026-09-16")
    assert f is not None
    assert f["model_version"] == "P1.0"
    # UNIQUE(game,target,model_version) prevents a second official freeze for the same model/draw.
    with db.connect() as con:
        n = con.execute("SELECT COUNT(*) FROM freezes WHERE game='649' AND target_draw_date='2026-09-16' AND model_version='P1.0'").fetchone()[0]
    assert n == 1


def test_olg_official_parser():
    from lottery_ai.providers import OLGOfficialProvider
    html='''<html><body>至爱游戏 中奖号码 Lotto Max 中奖号码 2026年9月11日
    01, 38, 41, 44, 45, 49, 51 特别号码 47 LOTTO 649 中奖号码 2026年9月9日
    14, 18, 27, 35, 41, 47 特别号码 17</body></html>'''
    d=OLGOfficialProvider.parse_html('max',html)
    assert d['date']=='2026-09-11' and d['numbers']==[1,38,41,44,45,49,51] and d['bonus']==47
    d=OLGOfficialProvider.parse_html('649',html)
    assert d['date']=='2026-09-09' and d['numbers']==[14,18,27,35,41,47] and d['bonus']==17


def test_lottodatabase_history_parser():
    from lottery_ai.providers import LottoDatabaseHistoryProvider
    html='''<html><body><h3>Wednesday, September 9, 2026</h3><div>14 18 27 35 41 47 17</div><div>Bonus</div>
    <h3>Saturday, September 5, 2026</h3><div>5 10 17 34 42 49 44</div><div>Bonus</div></body></html>'''
    rows=LottoDatabaseHistoryProvider.parse_html('649',html,'x')
    assert len(rows)==2
    assert rows[-1]['date']=='2026-09-09' and rows[-1]['bonus']==17


def test_lottonet_history_parser():
    from lottery_ai.providers import LottoNetHistoryProvider
    html='''<html><body><h3>Friday September 11th 2026</h3><p>Jackpot CA$30,000,000</p>
    <ul><li>1</li><li>38</li><li>41</li><li>44</li><li>45</li><li>49</li><li>51</li><li>47</li></ul><div>Bonus</div></body></html>'''
    rows=LottoNetHistoryProvider.parse_html('max',html,'x')
    assert len(rows)==1 and rows[0]['numbers']==[1,38,41,44,45,49,51] and rows[0]['bonus']==47


def test_expected_draw_calendar():
    from lottery_ai.updater import DataUpdater
    # 6/49 stayed Saturday-only through Sep 7, 1985; first Wednesday draw was Sep 11.
    early=DataUpdater.expected_draw_dates('649', __import__('datetime').date(1985,9,13))
    assert '1985-08-31' in early and '1985-09-04' not in early and '1985-09-07' in early and '1985-09-11' in early
    # Lotto Max began Friday-only; Tuesday was added May 14 2019.
    mx=DataUpdater.expected_draw_dates('max', __import__('datetime').date(2019,5,17))
    assert '2019-05-10' in mx and '2019-05-14' in mx and '2019-05-17' in mx


def test_unverified_history_cannot_overwrite_verified(tmp_path):
    from lottery_ai.db import Database
    db=Database(tmp_path/'x.db')
    db.upsert_draw('649','2026-09-09','649_CLASSIC',[14,18,27,35,41,47],17,'WCLC official',verified=True)
    db.upsert_draw('649','2026-09-09','649_CLASSIC',[1,2,3,4,5,6],7,'bad history',verified=False)
    d=db.draw_by_date('649','2026-09-09')
    assert d['numbers']==[14,18,27,35,41,47] and d['bonus']==17 and d['verified'] is True


def test_historical_max_date_aware_validation():
    from lottery_ai.providers import validate_draw_for_date
    assert validate_draw_for_date('max','2019-05-10',[1,2,3,4,5,6,49],7)
    assert not validate_draw_for_date('max','2019-05-10',[1,2,3,4,5,6,50],7)
    assert validate_draw_for_date('max','2019-05-14',[1,2,3,4,5,6,50],7)
    assert not validate_draw_for_date('max','2026-04-10',[1,2,3,4,5,6,51],7)
    assert validate_draw_for_date('max','2026-04-14',[1,2,3,4,5,6,51],7)


def test_github_csv_sch2000_layout():
    from lottery_ai.providers import GitHubCsvHistoryProvider
    text = "PlayDate,No1,No2,No3,No4,No5,No6,No7,Bonus,Jackpot\n2020-05-08,1,2,3,4,5,6,50,7,1000000\n"
    rows=GitHubCsvHistoryProvider.parse_csv('max',text,'sch2000','x')
    assert len(rows)==1 and rows[0]['date']=='2020-05-08' and rows[0]['numbers'][-1]==50


def test_github_csv_official_style_layout():
    from lottery_ai.providers import GitHubCsvHistoryProvider
    text = "PRODUCT,DRAW NUMBER,SEQUENCE NUMBER,DRAW DATE,NUMBER DRAWN 1,NUMBER DRAWN 2,NUMBER DRAWN 3,NUMBER DRAWN 4,NUMBER DRAWN 5,NUMBER DRAWN 6,BONUS NUMBER\nLOTTO 649,1,0,06/12/1982,3,11,12,14,41,43,13\n"
    rows=GitHubCsvHistoryProvider.parse_csv('649',text,'lotto88ai','x')
    assert len(rows)==1 and rows[0]['date']=='1982-06-12' and rows[0]['bonus']==13


def test_github_csv_packed_numbers_layout():
    from lottery_ai.providers import GitHubCsvHistoryProvider
    text = "Result Date,Numbers,Bonus Number,Prize,Rollover\n2009-Dec-25 Friday,\"['8', '9', '17', '24', '31', '39', '49']\",47,10000000,0\n"
    rows=GitHubCsvHistoryProvider.parse_csv('max',text,'msubin','x')
    assert len(rows)==1 and rows[0]['date']=='2009-12-25' and rows[0]['numbers']==[8,9,17,24,31,39,49]


def test_github_csv_lottomax_official_ddmmyyyy_and_sequence_filter():
    from lottery_ai.providers import GitHubCsvHistoryProvider
    text = "PRODUCT,DRAW NUMBER,SEQUENCE NUMBER,DRAW DATE,NUMBER DRAWN 1,NUMBER DRAWN 2,NUMBER DRAWN 3,NUMBER DRAWN 4,NUMBER DRAWN 5,NUMBER DRAWN 6,NUMBER DRAWN 7,BONUS NUMBER\nLOTTO MAX,1,0,25/09/2009,5,17,19,25,31,38,46,4\nLOTTO MAX,1,1,25/09/2009,1,2,3,4,5,6,7,0\n"
    rows=GitHubCsvHistoryProvider.parse_csv('max',text,'medikid','x')
    assert len(rows)==1 and rows[0]['date']=='2009-09-25' and rows[0]['bonus']==4


def test_wclc_since_inception_parser_649():
    from lottery_ai.providers import WCLCSinceInceptionProvider
    text = '''Page 48 LOTTO 6/49 SINCE INCEPTION Bonus GPD THE PLUS/EXTRA
September 6, 2006 3 8 20 26 37 46 27 4093046 EXTRA
September 9, 2006 13 22 31 32 34 48 26 6809825 EXTRA
September 13, 2006 19 30 32 33 38 41 14 1941102 EXTRA
'''
    rows = WCLCSinceInceptionProvider.parse_text('649', text, 'official')
    by = {r['date']: r for r in rows}
    assert by['2006-09-09']['numbers'] == [13,22,31,32,34,48]
    assert by['2006-09-09']['bonus'] == 26
    assert by['2006-09-09']['verified'] is True


def test_649_official_calendar_audit_and_model_quarantine(tmp_path):
    from lottery_ai.db import Database
    from lottery_ai.updater import DataUpdater
    db = Database(tmp_path/'audit.db')
    # One valid official-calendar row and one bogus off-calendar unverified row.
    db.upsert_draw('649','2006-09-06','649_CLASSIC',[3,8,20,26,37,46],27,'history',verified=False)
    db.upsert_draw('649','2006-09-07','649_CLASSIC',[1,2,3,4,5,6],7,'bad parser',verified=False)
    db.set_state('official_calendar_649',['2006-09-06','2006-09-09'])
    u = DataUpdater(db)
    h = u.audit_history('649')
    assert h['calendar_source'] == 'WCLC OFFICIAL ARCHIVE'
    assert '2006-09-09' in h['missing_dates']
    assert '2006-09-07' in h['unexpected_dates']
    assert '2006-09-07' in h['model_exclusions']
    usable = db.draws('649', era_only=True, model_ready=True)
    assert [x['draw_date'] for x in usable] == ['2006-09-06']


def test_official_history_wins_recovery_conflict(tmp_path):
    from lottery_ai.db import Database
    from lottery_ai.updater import DataUpdater
    db = Database(tmp_path/'merge.db')
    u = DataUpdater(db)
    rows = [
        {'date':'2006-09-09','numbers':[1,2,3,4,5,6],'bonus':7,'source':'third party','source_url':'x'},
        {'date':'2006-09-09','numbers':[13,22,31,32,34,48],'bonus':26,'source':'WCLC official since inception','source_url':'w','verified':True},
    ]
    result = u._merge_history_records('649', rows)
    d = db.draw_by_date('649','2006-09-09')
    assert d['numbers'] == [13,22,31,32,34,48]
    assert d['bonus'] == 26
    assert d['verified'] is True
    assert result['unresolved_conflicts'] == 0


def test_unresolved_conflict_is_quarantined_from_model(tmp_path):
    from lottery_ai.db import Database
    from lottery_ai.updater import DataUpdater
    db = Database(tmp_path/'conflict_audit.db')
    db.upsert_draw('649','2006-09-09','649_CLASSIC',[13,22,31,32,34,48],26,'unverified history',verified=False)
    db.set_state('official_calendar_649',['2006-09-09'])
    db.set_state('history_unresolved_conflicts_649',['2006-09-09'])
    h = DataUpdater(db).audit_history('649')
    assert '2006-09-09' in h['model_exclusions']
    assert db.draws('649', era_only=True, model_ready=True) == []


def test_wclc_since_inception_html_table_parser_649():
    from lottery_ai.providers import WCLCSinceInceptionProvider
    html = '''<table>
    <tr><td>September 6, 2006</td><td>3 8 20 26 37 46</td><td>27</td><td>4093046</td><td>EXTRA</td></tr>
    <tr><td>September 9, 2006</td><td>13 22 31 32 34 48</td><td>26</td><td>6809825</td><td>EXTRA</td></tr>
    </table>'''
    rows = WCLCSinceInceptionProvider.parse_html_table('649', html, 'official')
    assert len(rows) == 2
    assert rows[1]['date'] == '2006-09-09'
    assert rows[1]['numbers'] == [13,22,31,32,34,48]
    assert rows[1]['bonus'] == 26
    assert rows[1]['verified'] is True


def test_github_identity_gate_filters_non_canadian_calendar_rows():
    from lottery_ai.providers import GitHubCsvHistoryProvider
    # A Canadian source should be overwhelmingly Wed/Sat after 1985.
    rows = [
        {'date':'2023-12-27','numbers':[1,2,3,4,5,6],'bonus':7},
        {'date':'2023-12-30','numbers':[8,9,10,11,12,13],'bonus':14},
        {'date':'2023-12-28','numbers':[6,7,19,25,40,43],'bonus':8},  # Thu: non-Canadian pattern
    ]
    audit = GitHubCsvHistoryProvider.identity_audit('649', rows)
    assert audit['off_schedule'] == 1
    assert '2023-12-28' in audit['samples']


def test_649_schedule_fallback_quarantines_unverified_unexpected(tmp_path):
    from lottery_ai.db import Database
    from lottery_ai.updater import DataUpdater
    db = Database(tmp_path/'fallback_quarantine.db')
    db.upsert_draw('649','2023-12-27','649_CLASSIC',[2,10,16,17,24,26],18,'good history',verified=False)
    db.upsert_draw('649','2023-12-28','649_CLASSIC',[6,7,19,25,40,43],8,'foreign 6/49 contamination',verified=False)
    h = DataUpdater(db).audit_history('649')
    assert h['calendar_source'] == 'SCHEDULE FALLBACK'
    assert '2023-12-28' in h['unexpected_dates']
    assert '2023-12-28' in h['model_exclusions']
    usable = db.draws('649', era_only=True, model_ready=True)
    assert '2023-12-28' not in [x['draw_date'] for x in usable]


def test_wclc_pdf_line_parser_handles_special_dates_and_no_space_after_comma():
    from lottery_ai.providers import WCLCSinceInceptionProvider
    text = '''Page 142 LOTTO 6/49 SINCE INCEPTION Bonus GPD THE PLUS/EXTRA
September 15,2012 1 6 12 19 24 31 5 3225676 EXTRA
December 28, 2023 2 10 16 17 24 26 18 02681119-04W 3138979
December 31, 2023 2 5 7 11 15 21 25 03040528-01W 2096395
'''
    rows = WCLCSinceInceptionProvider.parse_text('649', text, 'official')
    by = {r['date']: r for r in rows}
    assert by['2012-09-15']['numbers'] == [1,6,12,19,24,31]
    assert by['2023-12-28']['bonus'] == 18
    assert by['2023-12-31']['verified'] is True


def test_649_fallback_treats_verified_off_schedule_draw_as_provisional_special(tmp_path):
    from lottery_ai.db import Database
    from lottery_ai.updater import DataUpdater
    db = Database(tmp_path/'special.db')
    db.upsert_draw('649','2023-12-27','649_CLASSIC',[1,2,3,4,5,6],7,'WCLC official',verified=True)
    db.upsert_draw('649','2023-12-28','649_CLASSIC',[2,10,16,17,24,26],18,'WCLC official since inception',verified=True)
    u = DataUpdater(db)
    u._canonical_expected_dates = lambda game_key, end_date=None: (['2023-12-27'], 'SCHEDULE FALLBACK')
    h = u.audit_history('649')
    assert h['provisional_special_dates'] == ['2023-12-28']
    assert h['expected'] == 2
    assert h['unexpected'] == 0
    assert h['model_exclusions'] == []
    assert h['model_data_status'] == 'CLEAN'
    assert h['usable_integrity_score'] == 100.0


def test_649_fallback_still_quarantines_unverified_off_schedule_artifact(tmp_path):
    from lottery_ai.db import Database
    from lottery_ai.updater import DataUpdater
    db = Database(tmp_path/'artifact.db')
    db.upsert_draw('649','2016-10-29','649_CLASSIC',[21,25,26,29,36,45],38,'official copy',verified=True)
    db.upsert_draw('649','2016-10-30','649_CLASSIC',[21,25,26,29,36,45],99,'GitHub historical recovery',verified=False)
    u = DataUpdater(db)
    u._canonical_expected_dates = lambda game_key, end_date=None: (['2016-10-29'], 'SCHEDULE FALLBACK')
    h = u.audit_history('649')
    assert h['unexpected_dates'] == ['2016-10-30']
    assert h['shifted_duplicate_dates'] == ['2016-10-30']
    assert h['unexpected_details'][0]['shift_strength'] == 'MAIN_NUMBERS'
    assert '2016-10-30' in h['model_exclusions']
    assert h['model_data_status'] == 'CLEAN'
    assert h['usable_integrity_score'] == 100.0


def test_max_fallback_quarantines_unverified_unexpected_and_keeps_archive_integrity(tmp_path):
    from lottery_ai.db import Database
    from lottery_ai.updater import DataUpdater
    db = Database(tmp_path/'max_artifact.db')
    db.upsert_draw('max','2026-04-14','MAX_52',[1,2,3,4,5,6,7],8,'official copy',verified=True)
    db.upsert_draw('max','2026-04-15','MAX_52',[1,2,3,4,5,6,7],8,'GitHub historical recovery',verified=False)
    u = DataUpdater(db)
    u._canonical_expected_dates = lambda game_key, end_date=None: (['2026-04-14'], 'SCHEDULE FALLBACK')
    h = u.audit_history('max')
    assert h['unexpected_dates'] == ['2026-04-15']
    assert '2026-04-15' in h['model_exclusions']
    assert h['model_ready_archive_draws'] == 1
    assert h['model_era_draws'] == 1
    assert h['model_era_expected'] == 1
    assert h['model_era_coverage_pct'] == 100.0
    assert h['model_data_status'] == 'CLEAN'
    assert h['usable_integrity_score'] == 100.0


def test_max_model_integrity_uses_archive_not_only_current_era(tmp_path):
    from lottery_ai.db import Database
    from lottery_ai.updater import DataUpdater
    db = Database(tmp_path/'max_integrity.db')
    db.upsert_draw('max','2019-05-17','MAX_50',[1,2,3,4,5,6,7],8,'history',verified=True)
    db.upsert_draw('max','2026-04-14','MAX_52',[8,9,10,11,12,13,14],15,'history',verified=True)
    u = DataUpdater(db)
    u._canonical_expected_dates = lambda game_key, end_date=None: (['2019-05-17','2026-04-14'], 'SCHEDULE FALLBACK')
    h = u.audit_history('max')
    assert h['model_ready_archive_draws'] == 2
    assert h['model_era_draws'] == 1
    assert h['model_era_expected'] == 1
    assert h['usable_integrity_score'] == 100.0
