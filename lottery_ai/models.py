from __future__ import annotations

from pathlib import Path
import hashlib
import os
import pickle
import warnings

from .config import GAMES, MIN_NN_DRAWS



def _trusted_pickle_load(path: Path):
    """Load only model snapshots written with a matching local SHA-256 sidecar.

    Pickle is code-bearing by design. Unsigned legacy/copied model files are ignored
    and retrained from audited draw data instead of being deserialized automatically.
    This is an integrity gate, not a substitute for OS-level trust if an attacker can
    modify both the model and its sidecar.
    """
    sig_path = path.with_suffix(path.suffix + ".sha256")
    if not sig_path.exists():
        raise ValueError("unsigned model snapshot")
    data = path.read_bytes()
    expected = sig_path.read_text(encoding="ascii").strip().lower()
    actual = hashlib.sha256(data).hexdigest()
    if expected != actual:
        raise ValueError("model snapshot hash mismatch")
    return pickle.loads(data)


def _trusted_pickle_save(path: Path, obj):
    """Write a signed model snapshot without exposing a half-written pickle.

    Both new payload files are prepared first. Normal write failures therefore leave the
    previous snapshot untouched. ``os.replace`` is atomic per file on supported local
    filesystems; if the sidecar replacement fails after the model replacement, the old
    pair is restored best-effort before re-raising.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    sig_path = path.with_suffix(path.suffix + ".sha256")
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_sig = sig_path.with_suffix(sig_path.suffix + ".tmp")
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    digest = hashlib.sha256(data).hexdigest()
    old_data = path.read_bytes() if path.exists() else None
    old_sig = sig_path.read_bytes() if sig_path.exists() else None
    replaced_model = False
    replaced_sig = False
    try:
        tmp_path.write_bytes(data)
        tmp_sig.write_text(digest, encoding="ascii")
        os.replace(tmp_path, path)
        replaced_model = True
        os.replace(tmp_sig, sig_path)
        replaced_sig = True
    except Exception:
        # Best-effort rollback for ordinary exceptions (not abrupt process/power loss).
        try:
            if replaced_model:
                if old_data is None:
                    path.unlink(missing_ok=True)
                else:
                    rollback = path.with_suffix(path.suffix + ".rollback")
                    rollback.write_bytes(old_data)
                    os.replace(rollback, path)
            if replaced_sig:
                if old_sig is None:
                    sig_path.unlink(missing_ok=True)
                else:
                    rollback_sig = sig_path.with_suffix(sig_path.suffix + ".rollback")
                    rollback_sig.write_bytes(old_sig)
                    os.replace(rollback_sig, sig_path)
        finally:
            tmp_path.unlink(missing_ok=True)
            tmp_sig.unlink(missing_ok=True)
        raise
    finally:
        tmp_path.unlink(missing_ok=True)
        tmp_sig.unlink(missing_ok=True)

try:
    import numpy as np
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.exceptions import ConvergenceWarning
except Exception:  # optional dependency
    np = None
    MLPClassifier = None
    StandardScaler = None
    ConvergenceWarning = Warning


class NeuralShadow:
    """Per-number shadow classifier. Production weight is always zero in V1.

    Each training row describes one number immediately before a historical draw;
    the target is whether that number appears in the next draw. This is deliberately
    small and regularized because lottery data is sparse/noisy.
    """
    def __init__(self, game_key: str, model_dir: str | Path):
        self.game_key = game_key
        self.cfg = GAMES[game_key]
        self.path = Path(model_dir) / f"nn_shadow_{game_key}.pkl"
        self.model = None
        self.scaler = None
        self.last_cutoff = None
        self.status = "UNAVAILABLE" if MLPClassifier is None else "NOT TRAINED"
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                obj = _trusted_pickle_load(self.path)
                self.model, self.scaler = obj["model"], obj["scaler"]
                self.last_cutoff = obj.get("last_cutoff")
                self.status = obj.get("status", "READY")
            except Exception:
                self.status = "MODEL LOAD ERROR"

    def _features_for_number(self, prior_sets, n):
        N = len(prior_sets)
        def rate(w):
            ss = prior_sets[-w:] if N >= w else prior_sets
            return sum(n in s for s in ss) / max(1, len(ss))
        gap = 0
        for s in reversed(prior_sets):
            if n in s:
                break
            gap += 1
        return [
            rate(10), rate(20), rate(50), rate(100),
            gap / max(1, min(N, 100)),
            n / self.cfg.max_number,
            float(n % 2),
            float(n > self.cfg.max_number/2),
        ]

    def train(self, draws):
        if MLPClassifier is None or np is None:
            self.status = "SKLEARN MISSING"
            return False
        if len(draws) < MIN_NN_DRAWS:
            self.status = f"WAITING ({len(draws)}/{MIN_NN_DRAWS} draws)"
            return False
        X, y = [], []
        sets = [set(d["numbers"]) for d in draws]
        # Limit to last 400 draw transitions for speed while keeping temporal variety.
        start = max(50, len(sets)-400)
        for i in range(start, len(sets)):
            prior = sets[:i]
            target = sets[i]
            for n in range(1, self.cfg.max_number+1):
                X.append(self._features_for_number(prior, n))
                y.append(1 if n in target else 0)
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=int)
        self.scaler = StandardScaler().fit(X)
        Xs = self.scaler.transform(X)
        self.model = MLPClassifier(
            hidden_layer_sizes=(32,16), activation="relu", alpha=0.02,
            max_iter=80, random_state=42, early_stopping=True,
            validation_fraction=0.15, n_iter_no_change=12
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            self.model.fit(Xs, y)
        self.status = "READY / SHADOW ONLY"
        self.last_cutoff = draws[-1].get("draw_date") if draws else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _trusted_pickle_save(self.path, {"model":self.model,"scaler":self.scaler,"status":self.status,"last_cutoff":self.last_cutoff})
        return True

    def needs_retrain(self, draws):
        return bool(draws) and len(draws) >= MIN_NN_DRAWS and self.last_cutoff != draws[-1].get("draw_date")

    def predict_scores(self, draws):
        if self.model is None or self.scaler is None or np is None:
            return {}
        sets = [set(d["numbers"]) for d in draws]
        X = [self._features_for_number(sets, n) for n in range(1,self.cfg.max_number+1)]
        probs = self.model.predict_proba(self.scaler.transform(np.asarray(X)))[:,1]
        lo, hi = float(probs.min()), float(probs.max())
        if hi <= lo:
            return {n:50.0 for n in range(1,self.cfg.max_number+1)}
        return {n:100*(float(probs[n-1])-lo)/(hi-lo) for n in range(1,self.cfg.max_number+1)}


class RegionNeuralShadow:
    """Shadow-only neural model for draw structure, not exact numbers.

    It predicts coarse sum, span and odd-count classes from rolling structural history.
    This model is intentionally excluded from Production scoring in V1.
    """
    def __init__(self, game_key: str, model_dir: str | Path):
        self.game_key = game_key
        self.cfg = GAMES[game_key]
        self.path = Path(model_dir) / f"region_nn_shadow_{game_key}.pkl"
        self.models = {}
        self.scaler = None
        self.last_cutoff = None
        self.status = "UNAVAILABLE" if MLPClassifier is None else "NOT TRAINED"
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                obj = _trusted_pickle_load(self.path)
                self.models = obj.get("models", {})
                self.scaler = obj.get("scaler")
                self.last_cutoff = obj.get("last_cutoff")
                self.status = obj.get("status", "READY")
            except Exception:
                self.status = "MODEL LOAD ERROR"

    def _one_draw_struct(self, d):
        a = sorted(d["numbers"])
        gaps = [b-a for a,b in zip(a,a[1:])]
        return {
            "sum": sum(a),
            "span": max(a)-min(a),
            "odd": sum(n%2 for n in a),
            "low": sum(n <= self.cfg.max_number/2 for n in a),
            "cons": sum(g==1 for g in gaps),
        }

    def _features(self, prior):
        rows=[self._one_draw_struct(d) for d in prior]
        exp_sum=self.cfg.pick*(self.cfg.max_number+1)/2
        out=[]
        for w in (10,20,50):
            r=rows[-w:] if len(rows)>=w else rows
            if not r:
                out += [1, .5, .5, .5, 0]
            else:
                out += [
                    sum(x["sum"] for x in r)/len(r)/exp_sum,
                    sum(x["span"] for x in r)/len(r)/self.cfg.max_number,
                    sum(x["odd"] for x in r)/len(r)/self.cfg.pick,
                    sum(x["low"] for x in r)/len(r)/self.cfg.pick,
                    sum(x["cons"] for x in r)/len(r)/max(1,self.cfg.pick-1),
                ]
        last=rows[-1]
        out += [last["sum"]/exp_sum,last["span"]/self.cfg.max_number,last["odd"]/self.cfg.pick]
        return out

    def needs_retrain(self, draws):
        return bool(draws) and len(draws)>=MIN_NN_DRAWS and self.last_cutoff != draws[-1].get("draw_date")

    def train(self, draws):
        if MLPClassifier is None or np is None:
            self.status="SKLEARN MISSING"; return False
        if len(draws)<MIN_NN_DRAWS:
            self.status=f"WAITING ({len(draws)}/{MIN_NN_DRAWS} draws)"; return False
        start=max(50,len(draws)-500)
        X=[]; targets={"sum":[],"span":[],"odd":[]}
        for i in range(start,len(draws)):
            X.append(self._features(draws[:i]))
            st=self._one_draw_struct(draws[i])
            targets["sum"].append(st["sum"]//15)
            targets["span"].append(st["span"]//5)
            targets["odd"].append(st["odd"])
        X=np.asarray(X,dtype=float)
        self.scaler=StandardScaler().fit(X)
        Xs=self.scaler.transform(X)
        self.models={}
        for name,y in targets.items():
            model=MLPClassifier(hidden_layer_sizes=(24,12),alpha=0.03,max_iter=100,
                                random_state=100+len(name),early_stopping=False)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                model.fit(Xs,np.asarray(y,dtype=int))
            self.models[name]=model
        self.status="READY / REGION SHADOW ONLY"
        self.last_cutoff=draws[-1].get("draw_date")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        _trusted_pickle_save(self.path, {"models":self.models,"scaler":self.scaler,
                                         "status":self.status,"last_cutoff":self.last_cutoff})
        return True

    def predict(self, draws):
        if not self.models or self.scaler is None or np is None:
            return {}
        X=self.scaler.transform(np.asarray([self._features(draws)],dtype=float))
        out={}
        for name,model in self.models.items():
            probs=model.predict_proba(X)[0]
            classes=model.classes_
            idx=int(np.argmax(probs))
            cls=int(classes[idx]); conf=float(probs[idx])
            if name=="sum": label=f"{cls*15}-{cls*15+14}"
            elif name=="span": label=f"{cls*5}-{cls*5+4}"
            else: label=str(cls)
            out[name]={"class":cls,"label":label,"shadow_confidence":round(conf,3)}
        return out
