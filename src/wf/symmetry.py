"""Period / two-family lag locator. No opcode catalogs.

Signals are repeated n-gram membership along .text: autocorrelation and
the periodogram read replica spacing; cross-correlation of two Jaccard
families reads the pairing offset. A single clone class is a trap.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np


@dataclass
class LocateResult:
    pairs: list[dict] = field(default_factory=list)
    dump: dict = field(default_factory=dict)


class _UF:
    def __init__(self, xs):
        self.p = {x: x for x in xs}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _key_period_stats(groups: dict) -> list[dict]:
    rows = []
    for key, spans in groups.items():
        if len(spans) < 3:
            continue
        addrs = np.array([a for a, _ in spans], dtype=float)
        deltas = np.diff(addrs)
        med = float(np.median(deltas))
        if med <= 0:
            continue
        cv = float(np.std(deltas) / med)
        rows.append(
            {
                "key": key,
                "n": len(spans),
                "spans": spans,
                "addrs": addrs,
                "med": med,
                "cv": cv,
            }
        )
    return rows


def _choose_period(rows: list[dict]) -> tuple[float | None, list[dict], dict]:
    periodic = [r for r in rows if r["cv"] <= 0.45 and r["med"] >= 16]
    meta: dict = {"n_periodic": len(periodic), "buckets": []}
    if not periodic:
        return None, [], meta
    max_n = max(r["n"] for r in periodic)
    keep = [r for r in periodic if r["n"] >= max(3, 0.30 * max_n)]
    buckets: dict[int, list] = defaultdict(list)
    for r in keep:
        b = int(round(r["med"] / 8.0) * 8)
        buckets[b].append(r)
    ranked = []
    for p, rs in buckets.items():
        nmax = max(r["n"] for r in rs)
        score = float(nmax**2) * p
        ranked.append((score, p, rs, nmax))
    ranked.sort(reverse=True)
    meta["buckets"] = [
        {"period": p, "score": score, "n_keys": len(rs), "max_copies": nmax}
        for score, p, rs, nmax in ranked[:8]
    ]
    if not ranked:
        return None, [], meta
    _, period, chosen, _ = ranked[0]
    return float(period), chosen, meta


def _merge_keys(groups: dict, snap: int, jaccard: float) -> list[dict]:
    keys = [k for k, v in groups.items() if v]
    if not keys:
        return []
    sites = {k: frozenset(((a + b) // 2) // snap for a, b in groups[k]) for k in keys}
    uf = _UF(keys)
    for i, k1 in enumerate(keys):
        s1 = sites[k1]
        if not s1:
            continue
        for k2 in keys[i + 1 :]:
            s2 = sites[k2]
            inter = len(s1 & s2)
            if not inter:
                continue
            if inter / len(s1 | s2) >= jaccard:
                uf.union(k1, k2)
    fam: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        fam[uf.find(k)].append(k)
    out = []
    for fid, ks in fam.items():
        hits = []
        for k in ks:
            hits.extend(groups[k])
        hits.sort()
        addrs = np.array([h[0] for h in hits], dtype=float)
        d = np.diff(addrs) if len(addrs) > 1 else np.array([np.nan])
        out.append(
            {
                "id": fid,
                "keys": ks,
                "n_keys": len(ks),
                "n_hits": len(hits),
                "hits": hits,
                "med_delta": float(np.nanmedian(d)),
                "sample": ks[0],
            }
        )
    out.sort(key=lambda f: -f["n_hits"])
    return out


def _phase_split(rows: list[dict], period: float) -> tuple[list[dict], list[dict]]:
    if len(rows) < 2 or not period:
        return rows, []
    phases = np.array([float(np.median(np.mod(r["addrs"], period))) for r in rows])
    ang = 2 * np.pi * phases / period
    X = np.stack([np.cos(ang), np.sin(ang)], axis=1)
    d = np.abs((phases[:, None] - phases[None, :] + period / 2) % period - period / 2)
    i, j = np.unravel_index(int(np.argmax(d)), d.shape)
    cents = X[[i, j]].copy()
    lab = np.zeros(len(rows), dtype=int)
    for _ in range(24):
        dist = ((X[:, None, :] - cents[None, :, :]) ** 2).sum(2)
        lab = dist.argmin(1)
        for k in (0, 1):
            if np.any(lab == k):
                v = X[lab == k].mean(0)
                nrm = np.linalg.norm(v) + 1e-12
                cents[k] = v / nrm
    a = [r for r, l in zip(rows, lab) if l == 0]
    b = [r for r, l in zip(rows, lab) if l == 1]
    if not a or not b:
        return rows, []
    return a, b


def _family_from_rows(rows: list[dict], tag: str) -> dict:
    hits = []
    keys = []
    for r in rows:
        hits.extend(r["spans"])
        keys.append(r["key"])
    hits.sort()
    addrs = np.array([h[0] for h in hits], dtype=float)
    d = np.diff(addrs) if len(addrs) > 1 else np.array([np.nan])
    return {
        "id": tag,
        "keys": keys,
        "n_keys": len(keys),
        "n_hits": len(hits),
        "hits": hits,
        "med_delta": float(np.nanmedian(d)),
        "sample": keys[0] if keys else "",
    }


def _raster_onsets(hits, lo: int, hi: int) -> np.ndarray:
    sig = np.zeros(max(1, hi - lo), dtype=np.float64)
    for a, _b in hits:
        if lo <= a < hi:
            sig[a - lo] = 1.0
    return sig


def _gauss_smooth(sig: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0 or sig.size == 0:
        return sig
    radius = int(max(3, 4 * sigma))
    x = np.arange(-radius, radius + 1)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    return np.convolve(sig, k, mode="same")


def _autocorr(sig: np.ndarray) -> np.ndarray:
    x = sig.astype(np.float64)
    if x.size == 0 or x.std() == 0:
        return np.zeros(1)
    x = x - x.mean()
    n = len(x)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    fx = np.fft.rfft(x, n=nfft)
    ac = np.fft.irfft(fx * np.conj(fx), n=nfft)[:n]
    if ac[0] != 0:
        ac = ac / ac[0]
    return ac


def _ac_peak(ac: np.ndarray, skip: int, limit: int | None = None) -> tuple[int, float]:
    if ac.size <= skip + 2:
        return 0, 0.0
    hi = min(ac.size, limit) if limit else ac.size
    sl = ac[skip:hi]
    if sl.size == 0:
        return 0, 0.0
    j = int(np.argmax(sl)) + skip
    return j, float(ac[j])


def _periodogram(sig: np.ndarray, pad: int = 1) -> tuple[np.ndarray, np.ndarray]:
    x = sig.astype(np.float64)
    if x.size < 8 or x.std() == 0:
        return np.array([0.0]), np.array([0.0])
    x = x - x.mean()
    win = np.hanning(len(x))
    nfft = int(2 ** np.ceil(np.log2(max(8, pad * len(x)))))
    spec = np.abs(np.fft.rfft(x * win, n=nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, d=1.0)
    spec[0] = 0.0
    return freqs, spec


def _fft_peak(freqs, spec, min_cycles: float, n_samples: int, prefer_period: float | None) -> dict:
    if spec.size == 0 or spec.max() <= 0:
        return {"period": None, "freq": None, "snr": 0.0}
    min_f = min_cycles / max(n_samples, 1)
    mask = freqs >= min_f
    if prefer_period and prefer_period > 0:
        band = (freqs >= 0.55 / prefer_period) & (freqs <= 1.55 / prefer_period)
        if np.any(band & (spec > 0)):
            mask = band
    idx = np.where(mask)[0]
    if idx.size == 0:
        idx = np.arange(1, spec.size)
    k = int(idx[np.argmax(spec[idx])])
    f = float(freqs[k])
    if f > 0:
        fmax = min(freqs[-1], max(6.0 * f, 4.0 / prefer_period)) if prefer_period else min(freqs[-1], 8.0 * f)
        rest = spec[(freqs >= min_f) & (freqs <= fmax) & ((freqs < 0.85 * f) | (freqs > 1.15 * f))]
        floor = float(np.mean(rest)) if rest.size else float(np.mean(spec[spec > 0]))
    else:
        floor = float(np.mean(spec[spec > 0])) if np.any(spec > 0) else 1.0
    if not np.isfinite(floor) or floor <= 0:
        floor = spec[k] / 50.0
    return {
        "period": (1.0 / f) if f > 0 else None,
        "freq": f,
        "snr": float(spec[k] / floor) if floor else 0.0,
    }


def _xcorr(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    if a.std() == 0 or b.std() == 0:
        return np.arange(1), np.zeros(1)
    a = a - a.mean()
    b = b - b.mean()
    n = len(a)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    fa = np.fft.rfft(a, n=nfft)
    fb = np.fft.rfft(b, n=nfft)
    c_full = np.fft.irfft(fa * np.conj(fb), n=nfft)
    c = np.concatenate([c_full[-(n - 1) :], c_full[:n]])
    c = c / (n * a.std() * b.std() + 1e-12)
    lags = np.arange(-n + 1, n)
    return lags, c[: lags.size]


def _dense_window(sig: np.ndarray) -> tuple[int, int]:
    if sig.size == 0 or sig.max() == 0:
        return 0, sig.size
    idx = np.flatnonzero(sig > 0)
    if idx.size == 0:
        return 0, sig.size
    pad = max(32, int(0.02 * sig.size))
    lo = max(0, int(idx[0]) - pad)
    hi = min(sig.size, int(idx[-1]) + pad)
    if hi - lo < 64:
        return 0, sig.size
    return lo, hi


def _downsample(sig: np.ndarray, n: int = 4096) -> list[float]:
    if sig.size == 0:
        return []
    if sig.size <= n:
        return [float(x) for x in sig]
    idx = np.linspace(0, sig.size - 1, n).astype(int)
    return [float(sig[i]) for i in idx]


def _fam_pub(fam: dict | None) -> dict | None:
    if not fam:
        return None
    keys = fam.get("keys") or []
    return {
        "id": fam.get("id"),
        "n_keys": fam.get("n_keys"),
        "n_hits": fam.get("n_hits"),
        "med_delta": fam.get("med_delta"),
        "sample": fam.get("sample"),
        "keys_head": keys[:8],
        "onsets": [a for a, _ in (fam.get("hits") or [])][:4096],
    }


def _pair_by_lag(
    fam_a: dict,
    fam_b: dict,
    lag: int,
    period: float | None,
    min_gap: int,
    max_gap: int,
    min_matches: int,
) -> list[dict]:
    if lag < min_gap or lag > max_gap:
        return []
    hits_a = sorted(fam_a["hits"])
    hits_b = sorted(fam_b["hits"])
    if not hits_a or not hits_b:
        return []
    tol = max(48, int(0.12 * period)) if period else 64
    used = set()
    regs = []
    gaps = []
    for a0, a1 in hits_a:
        best_i = None
        best_d = None
        for i, (b0, b1) in enumerate(hits_b):
            if i in used:
                continue
            d = min(abs(b0 - (a0 + lag)), abs(b0 - (a0 - lag)))
            if best_d is None or d < best_d:
                best_d, best_i = d, i
        if best_i is None or best_d is None or best_d > tol:
            continue
        used.add(best_i)
        b0, b1 = hits_b[best_i]
        regs.append((min(a0, b0), max(a1, b1)))
        gaps.append(abs(b0 - a0))
    if len(regs) < min_matches:
        return []
    n_matches = len(regs)
    out = []
    fa = str(fam_a.get("id") or fam_a.get("sample") or "A")
    fb = str(fam_b.get("id") or fam_b.get("sample") or "B")
    for (a, b), gap in zip(regs, gaps):
        out.append(
            {
                "start": a,
                "end": b,
                "family_a": fa,
                "family_b": fb,
                "n_matches": n_matches,
                "gap": int(gap),
            }
        )
    return out


def locate(groups: dict[str, list[tuple[int, int]]], insns, cfg: dict) -> LocateResult:
    """Two-family lag pairing from n-gram membership. Empty on a clone-class trap."""
    min_gap = int(cfg.get("min_gap", 64))
    max_gap = int(cfg.get("max_gap", 2048))
    min_count = int(cfg.get("min_count", 2))
    snap = int(cfg.get("snap", 16))
    jacc = float(cfg.get("jaccard", 0.4))
    pair_only = bool(cfg.get("pair_only", True))
    dump: dict = {
        "strategy": "symmetry",
        "n_repeated_keys": len(groups),
        "period": None,
        "autocorr_lag": None,
        "autocorr_R": None,
        "fft_period": None,
        "fft_snr": None,
        "xcorr_lag": None,
        "xcorr_peak": None,
        "trap_single_family": True,
        "vote": {},
        "families": [],
        "r_onsets": [],
        "r_signal": [],
        "family_signals": {},
    }
    empty = LocateResult(pairs=[], dump=dump)
    if not insns or not groups:
        return empty
    lo = insns[0].addr
    hi = insns[-1].addr + insns[-1].size
    rows = _key_period_stats(groups)
    period, period_rows, vote = _choose_period(rows)
    dump["vote"] = vote
    dump["period"] = period
    dump["period_key_count"] = len(period_rows)
    all_hits = [h for spans in groups.values() for h in spans]
    dump["r_onsets"] = [a for a, _ in all_hits][:50000]
    hero = max(period_rows, key=lambda r: r["n"]) if period_rows else None
    hero_hits = hero["spans"] if hero else []
    period_hits = [h for r in period_rows for h in r["spans"]]
    onsets = _raster_onsets(hero_hits or period_hits or all_hits, lo, hi)
    z0, z1 = _dense_window(onsets)
    on_z = onsets[z0:z1]
    if period:
        sigma = float(np.clip(period * 0.035, 1.4, 18.0))
    else:
        sigma = 8.0
    smooth = _gauss_smooth(on_z if on_z.max() > 0 else onsets[z0:z1], sigma)
    dump["r_signal"] = {
        "lo": lo + z0,
        "hi": lo + z1,
        "sigma": sigma,
        "downsampled": _downsample(smooth),
    }
    ac = _autocorr(smooth)
    skip = int(np.clip((period or 64) * 0.18, 8, max(12, (period or 64) * 0.42)))
    limit = min(ac.size, int((period or 256) * 8) if period else max(ac.size // 2, skip + 8))
    lag_ac, R = _ac_peak(ac, skip=skip, limit=max(skip + 8, limit))
    dump["autocorr_lag"] = int(lag_ac)
    dump["autocorr_R"] = float(R)
    freqs, spec = _periodogram(smooth, pad=1)
    peak = _fft_peak(freqs, spec, min_cycles=2.0, n_samples=len(smooth), prefer_period=period)
    dump["fft_period"] = peak["period"]
    dump["fft_snr"] = peak["snr"]

    near_rows = period_rows
    if period:
        extra = [
            r
            for r in rows
            if r["n"] >= 3 and r["cv"] <= 0.45 and abs(r["med"] - period) / period < 0.22
        ]
        if len(extra) > len(near_rows):
            near_rows = extra
    fam_groups = {r["key"]: r["spans"] for r in near_rows} if near_rows else {}
    families = _merge_keys(fam_groups, snap, jacc) if fam_groups else []
    dump["families"] = [_fam_pub(f) for f in families[:16]]
    if period and families:
        near = [
            f
            for f in families
            if np.isfinite(f["med_delta"]) and abs(f["med_delta"] - period) / max(period, 1) < 0.35
        ]
        near = near or families[:2]
    else:
        near = families[:2]
    near = sorted(near, key=lambda f: -f["n_hits"])[:2]
    if len(near) < 2 and len(near_rows) >= 2 and period:
        ra, rb = _phase_split(near_rows, period)
        if ra and rb:
            near = [_family_from_rows(ra, "phase-a"), _family_from_rows(rb, "phase-b")]
    trap = len(near) < 2
    fam_a = near[0] if near else None
    fam_b = near[1] if len(near) > 1 else None
    lag_x = peak_x = None
    if fam_a and fam_b:
        fam_sigma = max(1.2, sigma * 0.7)
        sig_a = _gauss_smooth(_raster_onsets(fam_a["hits"], lo + z0, lo + z1), fam_sigma)
        sig_b = _gauss_smooth(_raster_onsets(fam_b["hits"], lo + z0, lo + z1), fam_sigma)
        dump["family_signals"] = {
            "a": {"id": fam_a["id"], "onsets": [h[0] for h in fam_a["hits"]][:4096], "n": fam_a["n_hits"]},
            "b": {"id": fam_b["id"], "onsets": [h[0] for h in fam_b["hits"]][:4096], "n": fam_b["n_hits"]},
            "smooth_a": _downsample(sig_a),
            "smooth_b": _downsample(sig_b),
        }
        lags, xc = _xcorr(sig_a, sig_b)
        if xc.size and np.isfinite(xc).any():
            k = int(np.argmax(xc))
            lag_x = int(lags[k])
            peak_x = float(xc[k])
            if lag_x < 0:
                fam_a, fam_b = fam_b, fam_a
                lag_x = -lag_x
        if fam_b["n_hits"] < 0.2 * max(1, fam_a["n_hits"]) or (peak_x is not None and peak_x < 0.2):
            trap = True
    dump["xcorr_lag"] = lag_x
    dump["xcorr_peak"] = peak_x
    dump["trap_single_family"] = trap
    dump["family_a"] = _fam_pub(fam_a)
    dump["family_b"] = _fam_pub(fam_b)

    if trap or fam_a is None or fam_b is None or lag_x is None:
        if pair_only:
            return LocateResult(pairs=[], dump=dump)
        return LocateResult(pairs=[], dump=dump)

    pairs = _pair_by_lag(fam_a, fam_b, int(lag_x), period, min_gap, max_gap, min_count)
    dump["n_pairs"] = len(pairs)
    return LocateResult(pairs=pairs, dump=dump)
