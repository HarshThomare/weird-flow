#!/usr/bin/env python3
"""µWM localization as a classical symmetry / periodicity (DSP) problem.

Builds 1-D signals from ISA-agnostic n-grams (abstract registers, keep
immediates, drop nop-only keys) and plots autocorrelation, FFT, two-family
cross-correlation, and Eckmann recurrence. Detection never consults an
opcode trigger pack. DualGate / jmpreg symbols are loaded only to annotate
ground-truth spacing on the figures.

Does not import src/wf; the other agent owns the pipeline.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from elftools.elf.elffile import ELFFile
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MINER_DIR = ROOT / "experiment" / "repeat miner"
sys.path.insert(0, str(MINER_DIR))
from miner import REG, disassemble, is_nop_key  # noqa: E402

N = 6
ABSTRACT_REGS = True
ABSTRACT_IMMS = False
DROP_NOP = True
MIN_COUNT = 2
EXEC = 0x4
OUT = HERE / "figures"
CLANG = Path("/tmp/llvm-17/bin/clang-17")
BUILD = Path("/tmp/repeat-miner-build")

INK = "#1b1b1b"
BLUE = "#0072B2"
VERM = "#D55E00"
GREEN = "#009E73"
SKY = "#56B4E9"
GOLD = "#E69F00"
PURPLE = "#CC79A7"
PAPER = "#fbfaf6"
GRID = "#e6e2d8"


def style() -> None:
    mpl.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": PAPER,
            "axes.edgecolor": INK,
            "axes.labelcolor": INK,
            "axes.titlecolor": INK,
            "text.color": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.axisbelow": True,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 11.5,
            "axes.labelsize": 10.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "savefig.bbox": "tight",
            "savefig.facecolor": "white",
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )


def norm_insn(ins, abstract_regs: bool = True, abstract_imms: bool = False) -> str:
    op = ins.op
    if abstract_regs:
        op = REG.sub("REG", op)
    if abstract_imms:
        from miner import IMM

        op = IMM.sub("IMM", op)
    return ins.mnemonic if not op else f"{ins.mnemonic} {op}"


def load_view(path: Path) -> tuple[list, list[tuple[int, int, str]], str]:
    """Executable instructions plus optional DualGate/jmpreg spans for annotation."""
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        reloc = elf["e_type"] == "ET_REL"
        machine = elf["e_machine"]
        if machine in ("EM_X86_64", 62):
            arch = "x86"
        elif machine in ("EM_AARCH64", 183):
            arch = "arm64"
        elif machine in ("EM_RISCV", 243):
            arch = "riscv"
        else:
            arch = "x86"
        cursor = 0
        sections = []
        for idx, sec in enumerate(elf.iter_sections()):
            if not (int(sec["sh_flags"]) & EXEC and sec.data()):
                continue
            base = cursor if reloc else int(sec["sh_addr"])
            sections.append((idx, base, sec.data(), sec.name))
            if reloc:
                cursor += len(sec.data())
        insns = []
        for _, base, data, _ in sections:
            insns.extend(disassemble(data, base, arch))
        insns.sort(key=lambda i: i.addr)
        by_idx = {idx: base for idx, base, _, _ in sections}
        gates = []
        sym = elf.get_section_by_name(".symtab")
        if sym is not None:
            for s in sym.iter_symbols():
                name = s.name or ""
                shndx = s["st_shndx"]
                if shndx not in by_idx:
                    continue
                keep = (
                    "DualGate" in name
                    or name.startswith("jmpreg")
                    or name.startswith("__DualGate")
                )
                if not keep:
                    continue
                val = by_idx[shndx] + int(s["st_value"]) if reloc else int(s["st_value"])
                size = int(s["st_size"]) or (32 if name.startswith("jmpreg") else 0)
                if size <= 0:
                    continue
                gates.append((val, size, name))
        gates.sort()
    return insns, gates, arch


def ngram_groups(insns, n: int = N) -> dict[str, list[tuple[int, int, int]]]:
    """key -> list of (start_idx, start_addr, end_addr)."""
    norms = [norm_insn(i, ABSTRACT_REGS, ABSTRACT_IMMS) for i in insns]
    groups: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for i in range(0, len(insns) - n + 1):
        key = "|".join(norms[i : i + n])
        if DROP_NOP and is_nop_key(key):
            continue
        a = insns[i].addr
        z = insns[i + n - 1]
        groups[key].append((i, a, z.addr + z.size))
    return dict(groups)


def key_period_stats(groups: dict) -> list[dict]:
    rows = []
    for key, hits in groups.items():
        if len(hits) < 3:
            continue
        addrs = np.array([h[1] for h in hits], dtype=float)
        deltas = np.diff(addrs)
        med = float(np.median(deltas))
        if med <= 0:
            continue
        cv = float(np.std(deltas) / med)
        rows.append(
            {
                "key": key,
                "n": len(hits),
                "hits": hits,
                "addrs": addrs,
                "med": med,
                "cv": cv,
            }
        )
    return rows


def choose_period(rows: list[dict]) -> tuple[float | None, list[dict], dict]:
    """Dominant replica spacing: high copy-count keys, prefer a longer period.

    Score a spacing bucket by (max copies)^2 * period so a handful of DualGate
    clones beat a local unrolled loop, and a 1024-clone pad still wins on TAE.
    """
    periodic = [r for r in rows if r["cv"] <= 0.45 and r["med"] >= 16]
    meta = {"n_periodic": len(periodic), "buckets": []}
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


def merge_families(groups: dict, snap: int = 16, jaccard: float = 0.4) -> list[dict]:
    """Cluster n-gram keys whose occurrence sites overlap (same idiom)."""
    keys = [k for k, v in groups.items() if len(v) >= MIN_COUNT]
    if not keys:
        return []
    sites = {k: frozenset(((a + b) // 2) // snap for _, a, b in groups[k]) for k in keys}
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
        hits.sort(key=lambda h: h[1])
        addrs = np.array([h[1] for h in hits], dtype=float)
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


def byte_axis(insns) -> tuple[int, int]:
    lo = insns[0].addr
    hi = insns[-1].addr + insns[-1].size
    return lo, hi


def raster_onsets(hits, lo: int, hi: int) -> np.ndarray:
    sig = np.zeros(max(1, hi - lo), dtype=np.float64)
    for _, a, _ in hits:
        if lo <= a < hi:
            sig[a - lo] = 1.0
    return sig


def raster_cover(hits, lo: int, hi: int) -> np.ndarray:
    sig = np.zeros(max(1, hi - lo), dtype=np.float64)
    for _, a, b in hits:
        s = max(lo, a)
        e = min(hi, b)
        if e > s:
            sig[s - lo : e - lo] = 1.0
    return sig


def gauss_smooth(sig: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0 or sig.size == 0:
        return sig
    radius = int(max(3, 4 * sigma))
    x = np.arange(-radius, radius + 1)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    return np.convolve(sig, k, mode="same")


def autocorr(sig: np.ndarray) -> np.ndarray:
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


def ac_peak(ac: np.ndarray, skip: int, limit: int | None = None) -> tuple[int, float]:
    if ac.size <= skip + 2:
        return 0, 0.0
    hi = min(ac.size, limit) if limit else ac.size
    sl = ac[skip:hi]
    if sl.size == 0:
        return 0, 0.0
    j = int(np.argmax(sl)) + skip
    return j, float(ac[j])


def periodogram(sig: np.ndarray, pad: int = 4) -> tuple[np.ndarray, np.ndarray]:
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


def fft_peak(
    freqs: np.ndarray,
    spec: np.ndarray,
    min_cycles: float,
    n_samples: int,
    prefer_period: float | None = None,
) -> dict:
    if spec.size == 0 or spec.max() <= 0:
        return {"period": None, "freq": None, "snr": 0.0, "k": 0}
    min_f = min_cycles / max(n_samples, 1)
    mask = freqs >= min_f
    if prefer_period and prefer_period > 0:
        # Stay on the fundamental of the replica spacing (not a harmonic).
        band = (freqs >= 0.55 / prefer_period) & (freqs <= 1.55 / prefer_period)
        if np.any(band & (spec > 0)):
            mask = band
    idx = np.where(mask)[0]
    if idx.size == 0:
        idx = np.arange(1, spec.size)
    k = int(idx[np.argmax(spec[idx])])
    f = float(freqs[k])
    # Visual SNR: peak vs median of the rest of the spectrum in a few
    # fundamentals' worth of bandwidth (padded FFTs are numerically ~0
    # almost everywhere, which inflates median-based SNR into 1e11).
    if f > 0:
        fmax = min(freqs[-1], max(6.0 * f, 4.0 / prefer_period)) if prefer_period else min(freqs[-1], 8.0 * f)
        band = (freqs >= min_f) & (freqs <= fmax)
        rest = spec[band & ((freqs < 0.85 * f) | (freqs > 1.15 * f))]
        floor = float(np.mean(rest)) if rest.size else float(np.mean(spec[spec > 0]))
    else:
        floor = float(np.mean(spec[spec > 0])) if np.any(spec > 0) else 1.0
    if not np.isfinite(floor) or floor <= 0:
        floor = spec[k] / 50.0
    return {
        "period": (1.0 / f) if f > 0 else None,
        "freq": f,
        "snr": float(spec[k] / floor) if floor else 0.0,
        "power": float(spec[k]),
        "k": k,
    }


def xcorr(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
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
    # lags: 0 .. n-1 then wrap as negative lags
    c = np.concatenate([c_full[-(n - 1) :], c_full[:n]])
    c = c / (n * a.std() * b.std() + 1e-12)
    lags = np.arange(-n + 1, n)
    return lags, c[: lags.size]


def dense_window(sig: np.ndarray, win: int | None = None) -> tuple[int, int]:
    """Address range (relative) where the pulse train is concentrated."""
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


def gt_period(gates: list) -> float | None:
    if len(gates) < 2:
        return None
    starts = np.array([g[0] for g in gates], dtype=float)
    return float(np.median(np.diff(starts)))


def short_key(key: str, n: int = 72) -> str:
    text = key.replace("|", " · ")
    return text if len(text) <= n else text[: n - 1] + "…"


def phase_split(rows: list[dict], period: float) -> tuple[list[dict], list[dict]]:
    """Split same-period keys into two motifs by phase modulo P (circular 2-means)."""
    if len(rows) < 2 or not period:
        return rows, []
    phases = np.array([float(np.median(np.mod(r["addrs"], period))) for r in rows])
    ang = 2 * np.pi * phases / period
    X = np.stack([np.cos(ang), np.sin(ang)], axis=1)
    # seeds: two most separated phases
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


def family_from_rows(rows: list[dict], tag: str) -> dict:
    hits = []
    keys = []
    for r in rows:
        hits.extend(r["hits"])
        keys.append(r["key"])
    hits.sort(key=lambda h: h[1])
    addrs = np.array([h[1] for h in hits], dtype=float)
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


def eckmann(sig: np.ndarray, max_n: int = 420, eps_frac: float = 0.22) -> np.ndarray:
    """Barcode recurrence: dark where two replica pulses both fire."""
    del eps_frac
    if sig.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    if sig.size > max_n:
        step = int(np.ceil(sig.size / max_n))
        n = sig.size // step
        s = sig[: n * step].reshape(n, step).max(1)
    else:
        s = sig.astype(np.float64)
    if s.max() <= 0:
        return np.zeros((max(1, s.size), max(1, s.size)), dtype=np.uint8)
    on = (s >= 0.32 * s.max()).astype(np.uint8)
    return np.outer(on, on)


@dataclass
class Result:
    label: str
    path: str
    n_insns: int
    text_bytes: int
    n_gates: int
    gt_period: float | None
    n_repeated_keys: int
    period: float | None
    period_keys: int
    ac_lag: int
    ac_R: float
    fft_period: float | None
    fft_snr: float
    n_families: int
    fam_a_hits: int
    fam_b_hits: int
    fam_a_sample: str
    fam_b_sample: str
    xcorr_lag: int | None
    xcorr_peak: float | None
    folded_lag: int | None
    trap_single_family: bool
    extra: dict = field(default_factory=dict)
    # plot payloads (not JSON)
    payload: dict = field(default_factory=dict, repr=False)


def analyze(path: Path, label: str) -> Result:
    print(f"analyze {label}: {path}", flush=True)
    insns, gates, arch = load_view(path)
    if not insns:
        raise SystemExit(f"no instructions in {path}")
    groups = ngram_groups(insns)
    repeated = {k: v for k, v in groups.items() if len(v) >= MIN_COUNT}
    rows = key_period_stats(repeated)
    period, period_rows, vote = choose_period(rows)
    lo, hi = byte_axis(insns)
    # 1-D covering of every repeated (drop-nop) n-gram
    all_hits = [h for hits in repeated.values() for h in hits]
    cover_all = raster_cover(all_hits, lo, hi)
    # Period DSP uses ONE motif's onsets (a Dirac comb). Mixing two motifs
    # inside a DualGate makes the first autocorr peak the intra-gate lag.
    hero = max(period_rows, key=lambda r: r["n"]) if period_rows else None
    hero_hits = hero["hits"] if hero else []
    period_hits = [h for r in period_rows for h in r["hits"]]
    onsets = raster_onsets(hero_hits or period_hits, lo, hi)
    cover_p = raster_cover(period_hits, lo, hi) if period_hits else np.zeros(max(1, hi - lo))
    z0, z1 = dense_window(onsets if onsets.max() > 0 else cover_all)
    on_z = onsets[z0:z1]
    if period:
        sigma = float(np.clip(period * 0.035, 1.4, 18.0))
    else:
        sigma = 8.0
    smooth = gauss_smooth(on_z if on_z.max() > 0 else cover_all[z0:z1], sigma)
    if smooth.max() == 0:
        smooth = gauss_smooth(cover_all[z0:z1], 8.0)
    ac = autocorr(smooth)
    skip = int(np.clip((period or 64) * 0.18, 8, max(12, (period or 64) * 0.42)))
    limit = min(ac.size, int((period or 256) * 8) if period else max(ac.size // 2, skip + 8))
    lag, R = ac_peak(ac, skip=skip, limit=max(skip + 8, limit))
    freqs, spec = periodogram(smooth, pad=4)
    freqs_n, spec_n = periodogram(smooth, pad=1)
    peak = fft_peak(freqs_n, spec_n, min_cycles=2.0, n_samples=len(smooth), prefer_period=period)
    # Keep the interpolated spectrum for plotting; stamp the native peak onto it.
    peak_disp = fft_peak(freqs, spec, min_cycles=2.0, n_samples=len(smooth), prefer_period=period)
    if peak_disp["freq"] is not None:
        peak["freq"] = peak_disp["freq"]
        peak["period"] = peak_disp["period"]
        peak["k"] = peak_disp["k"]

    # Two families: Jaccard-merge of keys near P, else a phase split.
    near_rows = period_rows
    if period:
        extra = [
            r
            for r in rows
            if r["n"] >= 3
            and r["cv"] <= 0.45
            and abs(r["med"] - period) / period < 0.22
        ]
        if len(extra) > len(near_rows):
            near_rows = extra
    fam_groups = {r["key"]: r["hits"] for r in near_rows} if near_rows else {}
    families = merge_families(fam_groups, snap=16, jaccard=0.4) if fam_groups else []
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
        ra, rb = phase_split(near_rows, period)
        if ra and rb:
            near = [family_from_rows(ra, "phase-a"), family_from_rows(rb, "phase-b")]
    trap = len(near) < 2
    fam_a = near[0] if near else None
    fam_b = near[1] if len(near) > 1 else None
    lag_x = peak_x = folded = None
    sig_a = sig_b = lags = xc = None
    fam_sigma = max(1.2, sigma * 0.7)
    if fam_a and fam_b:
        sig_a = gauss_smooth(raster_onsets(fam_a["hits"], lo + z0, lo + z1), fam_sigma)
        sig_b = gauss_smooth(raster_onsets(fam_b["hits"], lo + z0, lo + z1), fam_sigma)
        lags, xc = xcorr(sig_a, sig_b)
        if xc.size and np.isfinite(xc).any():
            k = int(np.argmax(xc))
            lag_x = int(lags[k])
            peak_x = float(xc[k])
            if period and period > 0:
                folded = int(abs(lag_x) % int(round(period)))
                folded = min(folded, int(round(period)) - folded)
            if lag_x < 0:
                fam_a, fam_b = fam_b, fam_a
                sig_a, sig_b = sig_b, sig_a
                lag_x = -lag_x
                lags = -lags[::-1]
                xc = xc[::-1]
        if fam_b["n_hits"] < 0.2 * max(1, fam_a["n_hits"]) or (peak_x is not None and peak_x < 0.2):
            trap = True

    rec = eckmann(smooth, max_n=440)

    payload = {
        "insns": insns,
        "gates": gates,
        "lo": lo,
        "hi": hi,
        "z0": z0,
        "z1": z1,
        "cover_all": cover_all,
        "cover_p": cover_p,
        "onsets": onsets,
        "smooth": smooth,
        "ac": ac,
        "freqs": freqs,
        "spec": spec,
        "peak": peak,
        "sig_a": sig_a,
        "sig_b": sig_b,
        "x_lags": lags,
        "x_c": xc,
        "rec": rec,
        "period_rows": period_rows,
        "families": families,
        "fam_a": fam_a,
        "fam_b": fam_b,
        "sigma": sigma,
        "arch": arch,
        "vote": vote,
    }
    gt_p = gt_period(gates)
    return Result(
        label=label,
        path=str(path),
        n_insns=len(insns),
        text_bytes=hi - lo,
        n_gates=len(gates),
        gt_period=gt_p,
        n_repeated_keys=len(repeated),
        period=period,
        period_keys=len(period_rows),
        ac_lag=int(lag),
        ac_R=float(R),
        fft_period=peak["period"],
        fft_snr=float(peak["snr"]),
        n_families=len(families),
        fam_a_hits=int(fam_a["n_hits"]) if fam_a else 0,
        fam_b_hits=int(fam_b["n_hits"]) if fam_b else 0,
        fam_a_sample=short_key(fam_a["sample"]) if fam_a else "",
        fam_b_sample=short_key(fam_b["sample"]) if fam_b else "",
        xcorr_lag=lag_x,
        xcorr_peak=peak_x,
        folded_lag=folded,
        trap_single_family=trap,
        extra={"vote": vote, "n_families_near_period": len(near), "zoom_bytes": z1 - z0, "sigma": sigma},
        payload=payload,
    )


def recurrence_keys(insns, lo: int, hi: int, n: int = N) -> tuple[np.ndarray, list[str]]:
    """n-gram key starting at each instruction in [lo, hi), including nops."""
    slice_ins = [i for i in insns if lo <= i.addr < hi]
    if len(slice_ins) < n:
        return np.array([]), []
    norms = [norm_insn(i, True, False) for i in slice_ins]
    keys = []
    addrs = []
    for i in range(len(slice_ins) - n + 1):
        keys.append("|".join(norms[i : i + n]))
        addrs.append(slice_ins[i].addr)
    return np.array(addrs, dtype=int), keys


def rec_matrix(keys: list[str], max_n: int = 560) -> tuple[np.ndarray, int]:
    if not keys:
        return np.zeros((1, 1), dtype=np.uint8), 1
    step = max(1, int(np.ceil(len(keys) / max_n)))
    sub = keys[::step]
    loc = defaultdict(list)
    for i, k in enumerate(sub):
        loc[k].append(i)
    m = np.zeros((len(sub), len(sub)), dtype=np.uint8)
    for idxs in loc.values():
        ii = np.array(idxs, dtype=int)
        m[np.ix_(ii, ii)] = 1
    return m, step


def save(fig: plt.Figure, stem: str) -> list[str]:
    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / f"{stem}.png"
    svg = OUT / f"{stem}.svg"
    fig.savefig(png, dpi=220)
    fig.savefig(svg)
    plt.close(fig)
    print(f"  wrote {png.name} {svg.name}", flush=True)
    return [str(png), str(svg)]


def fmt_snr(snr: float) -> str:
    if snr >= 1000:
        return f"{snr:.1e}"
    return f"{snr:.1f}"


def plot_waveform(res: Result, stem: str, claim: str | None = None) -> list[str]:
    p = res.payload
    z0, z1, lo = p["z0"], p["z1"], p["lo"]
    xs = np.arange(z0, z1) + lo
    cov = p["cover_p"][z0:z1]
    if cov.max() == 0:
        cov = p["cover_all"][z0:z1]
    on = p["onsets"][z0:z1]
    fig, ax = plt.subplots(figsize=(8.4, 3.15))
    ax.fill_between(xs, 0, cov, color=BLUE, alpha=0.28, step="pre", label="repeated n-gram cover")
    sm = p["smooth"]
    if sm.size == cov.size and sm.max() > 0:
        ax.plot(xs, sm / sm.max(), color=INK, lw=1.15, alpha=0.85, label="Gaussian envelope")
    if on.max() > 0:
        y = np.where(on > 0, 1.05, np.nan)
        ax.plot(xs, y, "|", color=VERM, ms=7, mew=1.1, label="replica onset")
    for g0, gsz, _ in p["gates"]:
        if z0 + lo <= g0 < z1 + lo:
            ax.axvline(g0, color=GOLD, lw=0.8, alpha=0.7, zorder=2)
    ax.set_xlim(xs[0], xs[-1])
    ax.set_ylim(-0.05, 1.22)
    ax.set_xlabel("address (bytes)")
    ax.set_ylabel("r(x)")
    title = claim or f"{res.label}: repeated n-grams form a spatial comb"
    if res.period:
        title = f"{title}  (P ≈ {res.period:.0f} B)"
    ax.set_title(title)
    ax.legend(frameon=False, loc="upper right", fontsize=8)
    fig.tight_layout()
    return save(fig, stem)


def plot_autocorr(res: Result, stem: str, claim: str | None = None) -> list[str]:
    ac = res.payload["ac"]
    P = res.period or res.ac_lag or 1
    horizon = int(min(ac.size - 1, max(8 * P, 4 * (res.ac_lag or P))))
    tau = np.arange(horizon)
    fig, ax = plt.subplots(figsize=(8.0, 3.2))
    ax.plot(tau, ac[:horizon], color=BLUE, lw=1.5)
    ax.fill_between(tau, 0, ac[:horizon], color=SKY, alpha=0.25)
    ax.axvline(res.ac_lag, color=VERM, ls="--", lw=1.3)
    ax.annotate(
        f"τ = {res.ac_lag} B\nR = {res.ac_R:.2f}",
        xy=(res.ac_lag, res.ac_R),
        xytext=(res.ac_lag + horizon * 0.08, min(0.95, res.ac_R + 0.18)),
        color=VERM,
        fontsize=9,
        arrowprops=dict(arrowstyle="->", color=VERM, lw=1.0),
    )
    if res.period:
        for k in (1, 2, 3):
            t = k * res.period
            if t < horizon:
                ax.axvline(t, color=GREEN, ls=":", lw=0.9, alpha=0.8)
    ax.set_xlim(0, horizon)
    ax.set_ylim(min(-0.15, float(ac[:horizon].min()) - 0.05), 1.05)
    ax.set_xlabel("lag τ (bytes)")
    ax.set_ylabel("R(τ)")
    ax.set_title(claim or f"{res.label}: autocorrelation peak is the gadget period")
    fig.tight_layout()
    return save(fig, stem)


def plot_periodogram(res: Result, stem: str, claim: str | None = None) -> list[str]:
    freqs, spec = res.payload["freqs"], res.payload["spec"]
    peak = res.payload["peak"]
    P = peak["period"] or res.period
    if spec.max() <= 0:
        fig, ax = plt.subplots(figsize=(8.0, 3.2))
        ax.set_title("empty spectrum")
        return save(fig, stem)
    # show up to ~8 cycles of the fundamental, or 0.05 /B
    fmax = 0.05
    if P:
        fmax = min(0.08, max(6.0 / P, 3.0 / P))
    m = freqs <= fmax
    y = spec / (spec.max() + 1e-18)
    fig, ax = plt.subplots(figsize=(8.0, 3.35))
    ax.plot(freqs[m], y[m], color=INK, lw=1.55)
    ax.fill_between(freqs[m], 0, y[m], color=BLUE, alpha=0.22)
    if peak["freq"] and peak["freq"] <= fmax:
        ax.axvline(peak["freq"], color=VERM, ls="--", lw=1.3)
        ax.annotate(
            f"f = {peak['freq']:.4f} B⁻¹\nP = {P:.1f} B\nSNR = {fmt_snr(peak['snr'])}",
            xy=(peak["freq"], 1.0),
            xytext=(peak["freq"] + fmax * 0.08, 0.72),
            color=VERM,
            fontsize=9,
            arrowprops=dict(arrowstyle="->", color=VERM, lw=1.0),
        )
    ax.set_xlim(0, fmax)
    ax.set_ylim(0, 1.08)
    ax.set_xlabel("spatial frequency (1/bytes)")
    ax.set_ylabel("normalized power")
    ax.set_title(claim or f"{res.label}: DualGate spacing is a single spectral line")
    fig.tight_layout()
    return save(fig, stem)


def plot_two_family(res: Result, stem: str) -> list[str]:
    p = res.payload
    fig, axes = plt.subplots(2, 1, figsize=(8.4, 5.4), gridspec_kw={"height_ratios": [1.15, 1.0]})
    ax, bx = axes
    z0, z1, lo = p["z0"], p["z1"], p["lo"]
    xs = np.arange(z1 - z0) + (lo + z0)
    if p["sig_a"] is None or p["sig_b"] is None:
        ax.text(0.5, 0.5, "single family — no pair lag", ha="center", transform=ax.transAxes)
        bx.text(0.5, 0.5, "n/a", ha="center", transform=bx.transAxes)
    else:
        a = p["sig_a"] / (p["sig_a"].max() + 1e-12)
        b = p["sig_b"] / (p["sig_b"].max() + 1e-12)
        ax.plot(xs, a, color=VERM, lw=1.3, label="family A")
        ax.plot(xs, b + 1.15, color=BLUE, lw=1.3, label="family B")
        ax.set_xlim(xs[0], xs[-1])
        ax.ticklabel_format(style="plain", axis="x", useOffset=False)
        ax.set_ylabel("membership")
        ax.set_xlabel("address (bytes)")
        ax.legend(frameon=False, ncol=2, loc="upper right", fontsize=8)
        ax.set_yticks([0.5, 1.65])
        ax.set_yticklabels(["A", "B"])
        lags, c = p["x_lags"], p["x_c"]
        P = res.period or 256
        m = (lags >= -2 * P) & (lags <= 2 * P)
        bx.plot(lags[m], c[m], color=INK, lw=1.4)
        bx.fill_between(lags[m], 0, c[m], color=GOLD, alpha=0.25)
        if res.xcorr_lag is not None:
            bx.axvline(res.xcorr_lag, color=VERM, ls="--", lw=1.3)
            bx.annotate(
                f"lag = {res.xcorr_lag} B\npeak = {res.xcorr_peak:.2f}",
                xy=(res.xcorr_lag, res.xcorr_peak or 0),
                xytext=(res.xcorr_lag + 0.08 * 2 * P, 0.6 * (res.xcorr_peak or 0.4) + 0.15),
                color=VERM,
                fontsize=9,
                arrowprops=dict(arrowstyle="->", color=VERM, lw=1.0),
            )
        bx.set_xlabel("lag (bytes)")
        bx.set_ylabel("cross-correlation")
    ax.set_title(
        f"{res.label}: two co-located n-gram families  ·  A: {res.fam_a_sample[:40]}"
    )
    fig.subplots_adjust(left=0.11, right=0.98, top=0.90, bottom=0.10, hspace=0.38)
    return save(fig, stem)


def plot_recurrence(res: Result, stem: str) -> list[str]:
    rec = res.payload.get("rec")
    if rec is None or rec.size == 0:
        fig, ax = plt.subplots(figsize=(6.4, 6.0))
        ax.set_title("empty recurrence")
        return save(fig, stem)
    fig, ax = plt.subplots(figsize=(6.5, 6.1))
    ax.imshow(1 - rec, cmap="gray", origin="upper", interpolation="nearest", vmin=0, vmax=1)
    n = rec.shape[0]
    ax.set_xlabel("i (along .text, downsampled)")
    ax.set_ylabel("j")
    ax.set_title(f"{res.label}: pulse×pulse recurrence — the DualGate copies form a lattice")
    ax.grid(False)
    ax.spines["top"].set_visible(True)
    ax.spines["right"].set_visible(True)
    P = res.period or res.gt_period
    z0, z1 = res.payload["z0"], res.payload["z1"]
    span = max(1, z1 - z0)
    if P and n > 24:
        n_show = max(18, int(n * min(1.0, (2.4 * P) / span)))
        n_show = min(n - 1, max(22, n_show))
        axins = inset_axes(ax, width="40%", height="40%", loc="lower left", borderpad=1.0)
        axins.imshow(
            1 - rec[:n_show, :n_show],
            cmap="gray",
            origin="upper",
            interpolation="nearest",
            vmin=0,
            vmax=1,
        )
        axins.set_xticks([])
        axins.set_yticks([])
        axins.set_title("≈ two periods", fontsize=8, pad=2)
        axins.grid(False)
        mark_inset(ax, axins, loc1=1, loc2=2, fc="none", ec=VERM, lw=0.8)
    fig.subplots_adjust(left=0.12, right=0.98, top=0.92, bottom=0.10)
    return save(fig, stem)


def plot_spectrogram(res: Result, stem: str) -> list[str]:
    p = res.payload
    z0, z1, lo = p["z0"], p["z1"], p["lo"]
    sig = p["onsets"][z0:z1]
    if sig.max() == 0:
        sig = p["cover_p"][z0:z1]
    win = int(min(2048, max(256, sig.size // 6)))
    hop = max(32, win // 8)
    if sig.size < win + hop:
        return []
    W = np.hanning(win)
    nfft = win * 2
    cols = []
    for start in range(0, sig.size - win, hop):
        x = (sig[start : start + win] - sig[start : start + win].mean()) * W
        cols.append(np.abs(np.fft.rfft(x, n=nfft)) ** 2)
    S = np.array(cols).T
    freqs = np.fft.rfftfreq(nfft, 1.0)
    P = res.period or res.fft_period
    fmax = min(0.04, 5.0 / P) if P else 0.02
    fm = freqs <= fmax
    S = S[fm]
    S = S / (S.max() + 1e-18)
    extent = [lo + z0, lo + z0 + sig.size, 0, fmax]
    fig, ax = plt.subplots(figsize=(8.2, 3.4))
    ax.imshow(S, origin="lower", aspect="auto", extent=extent, cmap="magma")
    if P:
        ax.axhline(1.0 / P, color="white", ls="--", lw=1.1, alpha=0.9)
        ax.text(extent[0] + 0.02 * (extent[1] - extent[0]), 1.0 / P, f"  1/{P:.0f} B", color="white", va="bottom", fontsize=9)
    ax.set_xlabel("address (bytes)")
    ax.set_ylabel("spatial frequency (1/bytes)")
    ax.set_title(f"{res.label}: spectrogram of the replica comb")
    ax.grid(False)
    fig.tight_layout()
    return save(fig, stem)


def plot_combined(res: Result, stem: str) -> list[str]:
    p = res.payload
    z0, z1, lo = p["z0"], p["z1"], p["lo"]
    xs = np.arange(z0, z1) + lo
    cov = p["cover_p"][z0:z1]
    if cov.max() == 0:
        cov = p["cover_all"][z0:z1]
    fig = plt.figure(figsize=(11.2, 12.4))
    gs = fig.add_gridspec(4, 2, height_ratios=[1.05, 1.05, 1.15, 1.55], hspace=0.42, wspace=0.28)
    axw = fig.add_subplot(gs[0, :])
    axa = fig.add_subplot(gs[1, 0])
    axf = fig.add_subplot(gs[1, 1])
    axt = fig.add_subplot(gs[2, 0])
    axx = fig.add_subplot(gs[2, 1])
    axr = fig.add_subplot(gs[3, :])

    axw.fill_between(xs, 0, cov, color=BLUE, alpha=0.35, step="pre")
    on = p["onsets"][z0:z1]
    if on.max() > 0:
        axw.plot(xs, np.where(on > 0, 1.08, np.nan), "|", color=VERM, ms=6, mew=1.0)
    for g0, _, _ in p["gates"]:
        if xs[0] <= g0 <= xs[-1]:
            axw.axvline(g0, color=GOLD, lw=0.7, alpha=0.75)
    axw.set_xlim(xs[0], xs[-1])
    axw.set_ylim(-0.05, 1.25)
    axw.set_xlabel("address (bytes)")
    axw.set_ylabel("r(x)")
    Pshow = res.fft_period or res.period
    axw.set_title(
        f"{res.label}: translational symmetry of two copied idioms"
        + (f"  ·  FFT P = {Pshow:.0f} B" if Pshow else "")
    )

    ac = p["ac"]
    P = res.period or max(res.ac_lag, 64)
    horizon = int(min(ac.size - 1, max(6 * P, 3 * res.ac_lag)))
    tau = np.arange(horizon)
    axa.plot(tau, ac[:horizon], color=BLUE, lw=1.4)
    axa.fill_between(tau, 0, ac[:horizon], color=SKY, alpha=0.25)
    axa.axvline(res.ac_lag, color=VERM, ls="--", lw=1.2)
    axa.set_xlim(0, horizon)
    axa.set_xlabel("lag τ (bytes)")
    axa.set_ylabel("R(τ)")
    axa.set_title(f"autocorrelation  ·  τ = {res.ac_lag} B")

    freqs, spec = p["freqs"], p["spec"]
    peak = p["peak"]
    fmax = min(0.08, 6.0 / P) if P else 0.04
    m = freqs <= fmax
    y = spec / (spec.max() + 1e-18)
    axf.plot(freqs[m], y[m], color=INK, lw=1.45)
    axf.fill_between(freqs[m], 0, y[m], color=BLUE, alpha=0.22)
    if peak["freq"] and peak["freq"] < fmax:
        axf.axvline(peak["freq"], color=VERM, ls="--", lw=1.2)
    axf.set_xlim(0, fmax)
    axf.set_xlabel("spatial frequency (1/bytes)")
    axf.set_ylabel("power")
    snr = peak["snr"]
    axf.set_title(
        f"periodogram  ·  P = {peak['period']:.0f} B  ·  SNR {fmt_snr(snr)}" if peak["period"] else "periodogram"
    )

    if p["sig_a"] is not None and p["sig_b"] is not None:
        a = p["sig_a"] / (p["sig_a"].max() + 1e-12)
        b = p["sig_b"] / (p["sig_b"].max() + 1e-12)
        xrel = xs[: len(a)] - xs[0]
        axt.plot(xrel, a, color=VERM, lw=1.15, label="family A")
        axt.plot(xrel[: len(b)], b + 1.2, color=BLUE, lw=1.15, label="family B")
        axt.set_xlim(0, float(xrel[-1]) if xrel.size else 1)
        axt.set_yticks([0.45, 1.65])
        axt.set_yticklabels(["A", "B"])
        axt.legend(frameon=False, fontsize=8, loc="upper right")
        lags, c = p["x_lags"], p["x_c"]
        mm = (lags >= -2 * P) & (lags <= 2 * P)
        axx.plot(lags[mm], c[mm], color=INK, lw=1.3)
        axx.fill_between(lags[mm], 0, c[mm], color=GOLD, alpha=0.25)
        if res.xcorr_lag is not None:
            axx.axvline(res.xcorr_lag, color=VERM, ls="--", lw=1.2)
            axx.set_title(f"A⋆B  ·  lag = {res.xcorr_lag} B")
        else:
            axx.set_title("A⋆B")
    else:
        axt.text(0.5, 0.5, "one family at this period", ha="center", transform=axt.transAxes)
        axx.text(0.5, 0.5, "no pair lag", ha="center", transform=axx.transAxes)
        axx.set_title("A⋆B")
    axt.set_title("two-family overlay")
    axt.set_xlabel("offset in replica region (bytes)")
    axx.set_xlabel("lag (bytes)")

    rec = p.get("rec")
    if rec is not None and rec.size:
        axr.imshow(1 - rec, cmap="gray", origin="upper", interpolation="nearest", vmin=0, vmax=1)
        axr.grid(False)
        axr.spines["top"].set_visible(True)
        axr.spines["right"].set_visible(True)
        axr.set_title("pulse×pulse recurrence — a lattice of DualGate copies")
        axr.set_xlabel("i")
        axr.set_ylabel("j")
        n = rec.shape[0]
        span = max(1, z1 - z0)
        if P and n > 24:
            n_show = max(16, int(n * min(1.0, (2.2 * P) / span)))
            n_show = min(n - 1, max(20, n_show))
            axins = inset_axes(axr, width="28%", height="55%", loc="lower left", borderpad=0.8)
            axins.imshow(
                1 - rec[:n_show, :n_show],
                cmap="gray",
                origin="upper",
                interpolation="nearest",
                vmin=0,
                vmax=1,
            )
            axins.set_xticks([])
            axins.set_yticks([])
            axins.grid(False)
            axins.set_title("inset", fontsize=8)
            mark_inset(axr, axins, loc1=1, loc2=2, fc="none", ec=VERM, lw=0.7)
    fig.suptitle(
        "Localization is a symmetry problem: a discrete spatial period along .text",
        fontsize=13,
        y=0.995,
    )
    return save(fig, stem)


def plot_negative_panel(simd: Result, other: Result, stem: str) -> list[str]:
    fig, axes = plt.subplots(2, 2, figsize=(9.6, 6.4))
    for col, res, name in ((0, simd, "SIMD clones"), (1, other, other.label)):
        ac = res.payload["ac"]
        empty = ac.size <= 1 or (ac.max() == 0 and (res.period is None))
        if empty:
            for row in (0, 1):
                axes[row, col].text(0.5, 0.5, "no periodic drop-nop n-grams", ha="center", va="center")
                axes[row, col].set_xticks([])
                axes[row, col].set_yticks([])
            axes[0, col].set_title(f"{name}: autocorrelation")
            axes[1, col].set_title(f"{name}: periodogram")
            continue
        P = res.period or max(res.ac_lag, 32)
        horizon = int(min(ac.size - 1, max(6 * P, 256)))
        axes[0, col].plot(np.arange(horizon), ac[:horizon], color=BLUE, lw=1.3)
        axes[0, col].set_title(f"{name}: autocorrelation")
        axes[0, col].set_xlabel("lag (bytes)")
        axes[0, col].set_ylabel("R(τ)")
        freqs, spec = res.payload["freqs"], res.payload["spec"]
        fmax = min(0.08, 8.0 / P) if P else 0.06
        m = freqs <= fmax
        y = spec / (spec.max() + 1e-18) if spec.max() > 0 else spec
        axes[1, col].plot(freqs[m], y[m], color=INK, lw=1.3)
        axes[1, col].fill_between(freqs[m], 0, y[m], color=PURPLE, alpha=0.25)
        axes[1, col].set_title(f"{name}: periodogram")
        axes[1, col].set_xlabel("1/bytes")
        axes[1, col].set_ylabel("power")
        axes[1, col].text(
            0.98,
            0.92,
            "single family — not a µWM pair",
            transform=axes[1, col].transAxes,
            ha="right",
            va="top",
            fontsize=8,
            color=VERM,
        )
    fig.suptitle("Hard negatives: repetition without two co-located µWM idioms", fontsize=13)
    fig.tight_layout()
    return save(fig, stem)


def plot_tae_trap(res: Result, stem: str) -> list[str]:
    p = res.payload
    z0, z1, lo = p["z0"], p["z1"], p["lo"]
    on = p["onsets"][z0:z1]
    sm = p["smooth"]
    P = res.period or 32
    fig, axes = plt.subplots(3, 1, figsize=(8.6, 8.4), gridspec_kw={"height_ratios": [1.05, 1.05, 1.2]})
    ax, bx, cx = axes
    # Zoom ~24 clone spacings so the Dirac comb is visible (full span is a slab).
    nshow = int(min(on.size, max(24 * P, 256)))
    mid = on.size // 2
    a0 = max(0, mid - nshow // 2)
    a1 = min(on.size, a0 + nshow)
    xs = np.arange(a0, a1) + (lo + z0)
    ax.plot(xs, sm[a0:a1] / (sm.max() + 1e-12), color=INK, lw=1.2)
    ax.fill_between(xs, 0, on[a0:a1], color=VERM, alpha=0.45, step="pre")
    ax.set_xlim(xs[0], xs[-1])
    ax.set_ylabel("onset")
    ax.set_xlabel("address (bytes), zoomed")
    ax.set_title("TAE gates.elf: 1024 jmpreg clones are a 32-byte Dirac comb (one family)")
    ac = p["ac"]
    horizon = int(min(ac.size - 1, 16 * P))
    bx.plot(np.arange(horizon), ac[:horizon], color=BLUE, lw=1.4)
    bx.axvline(res.ac_lag, color=VERM, ls="--")
    bx.set_xlabel("lag (bytes)")
    bx.set_ylabel("R(τ)")
    bx.set_title(f"autocorrelation of the clone class  ·  τ = {res.ac_lag} B  ·  R = {res.ac_R:.2f}")
    freqs, spec = p["freqs"], p["spec"]
    fmax = min(0.12, 6.0 / P)
    m = freqs <= fmax
    y = spec / (spec.max() + 1e-18)
    cx.plot(freqs[m], y[m], color=INK, lw=1.35)
    cx.fill_between(freqs[m], 0, y[m], color=VERM, alpha=0.2)
    if res.payload["peak"]["freq"]:
        cx.axvline(res.payload["peak"]["freq"], color=VERM, ls="--")
        cx.annotate(
            f"1/{P:.0f} B⁻¹",
            xy=(res.payload["peak"]["freq"], 1.0),
            xytext=(res.payload["peak"]["freq"] + 0.15 * fmax, 0.72),
            color=VERM,
            fontsize=9,
            arrowprops=dict(arrowstyle="->", color=VERM, lw=1.0),
        )
    note = "single family: this line is 1024 jmp-pads, not trigger+decode"
    cx.set_title(f"periodogram  ·  P = {res.fft_period:.1f} B  ·  {note}" if res.fft_period else note)
    cx.set_xlabel("spatial frequency (1/bytes)")
    cx.set_ylabel("power")
    fig.tight_layout()
    return save(fig, stem)


def result_public(res: Result) -> dict:
    d = {
        "label": res.label,
        "path": res.path,
        "n_insns": res.n_insns,
        "text_bytes": res.text_bytes,
        "n_gates_annotated": res.n_gates,
        "gt_period_bytes": res.gt_period,
        "n_repeated_keys": res.n_repeated_keys,
        "detected_period_bytes": res.period,
        "period_key_count": res.period_keys,
        "autocorr_lag_bytes": res.ac_lag,
        "autocorr_R": round(res.ac_R, 4),
        "fft_period_bytes": res.fft_period,
        "fft_snr_vs_median": round(res.fft_snr, 1),
        "n_families_total": res.n_families,
        "family_a_hits": res.fam_a_hits,
        "family_b_hits": res.fam_b_hits,
        "family_a_sample": res.fam_a_sample,
        "family_b_sample": res.fam_b_sample,
        "xcorr_lag_bytes": res.xcorr_lag,
        "xcorr_peak": None if res.xcorr_peak is None else round(res.xcorr_peak, 4),
        "folded_lag_bytes": res.folded_lag,
        "single_family_trap": res.trap_single_family,
        "extra": res.extra,
    }
    if res.fft_period:
        d["fft_period_bytes"] = round(res.fft_period, 2)
    return d


def maybe_compile_negatives() -> dict[str, Path]:
    out = {}
    jobs = {
        "neg_simd": (MINER_DIR / "negatives" / "simd_kernel.c", ["-O3", "-mavx2"]),
        "neg_crypto": (MINER_DIR / "negatives" / "unrolled_crypto.c", ["-O3"]),
        "neg_templates": (MINER_DIR / "negatives" / "templates.cpp", ["-O3", "-std=c++20"]),
    }
    BUILD.mkdir(parents=True, exist_ok=True)
    for label, (src, flags) in jobs.items():
        dest = BUILD / f"{label}.o"
        cached = {
            "neg_simd": BUILD / "neg-simd.o",
            "neg_crypto": BUILD / "neg-unrolled-crypto.o",
            "neg_templates": BUILD / "neg-templates.o",
        }[label]
        if cached.exists():
            out[label] = cached
            continue
        if dest.exists():
            out[label] = dest
            continue
        cc = str(CLANG if src.suffix != ".cpp" else Path("/tmp/llvm-17/bin/clang++-17"))
        cmd = [cc, "--gcc-install-dir=/usr/lib/gcc/x86_64-linux-gnu/11", "-c", *flags, str(src), "-o", str(dest)]
        import subprocess

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            out[label] = dest
        else:
            print(f"  negative compile failed {label}: {proc.stderr[-200:]}", flush=True)
    return out


def main() -> None:
    style()
    OUT.mkdir(parents=True, exist_ok=True)
    binaries = [
        ("flexo_test", ROOT / "third_party/flexo/circuits/gates/test.elf"),
        ("flexo_and", ROOT / "third_party/flexo/circuits/gates/and.elf"),
        ("flexo_alu", ROOT / "third_party/flexo/circuits/ALU/ALU.elf"),
        ("flexo_sbox", ROOT / "third_party/flexo/circuits/AES/sbox.elf"),
        ("flexo_tlb", ROOT / "third_party/tlb/Flexo/Flexo-TLB/circuits/gates/test.elf"),
        ("flexo_dcache", ROOT / "third_party/tlb/Flexo/Flexo-DCache/circuits/gates/test.elf"),
        ("gitm_and", Path("/u/hthomare/weird-machines/artifacts/WeMu/src/gates/gitm/and_timing.elf")),
        ("tae_gates", ROOT / "third_party/tae/elf/rerun1/gates.elf"),
    ]
    negs = maybe_compile_negatives()
    for k, p in negs.items():
        binaries.append((k, p))

    results: dict[str, Result] = {}
    for label, path in binaries:
        if not path.exists():
            print(f"skip missing {path}", flush=True)
            continue
        results[label] = analyze(path, label.replace("_", " "))

    written = []
    alu = results.get("flexo_alu")
    test = results.get("flexo_test")
    sbox = results.get("flexo_sbox")
    gitm = results.get("gitm_and")
    tae = results.get("tae_gates")
    dcache = results.get("flexo_dcache")
    tlb = results.get("flexo_tlb")
    simd = results.get("neg_simd")
    tmpl = results.get("neg_templates") or results.get("neg_crypto")

    if alu:
        written += plot_combined(alu, "flexo_alu_combined")
        written += plot_waveform(
            alu,
            "flexo_alu_waveform",
            "Flexo ALU: each DualGate is a pulse in a 1-bit repeatness comb",
        )
        written += plot_autocorr(
            alu,
            "flexo_alu_autocorr",
            "Flexo ALU: autocorrelation peak = DualGate spacing (same role as pitch)",
        )
        written += plot_periodogram(
            alu,
            "flexo_alu_periodogram",
            "Flexo ALU DualGate spacing is a single spectral line",
        )
        written += plot_two_family(alu, "flexo_alu_two_family")
        written += plot_recurrence(alu, "flexo_alu_recurrence")
        written += plot_spectrogram(alu, "flexo_alu_spectrogram")
    if test:
        written += plot_waveform(
            test,
            "flexo_test_waveform",
            "Flexo test.elf: copied n-grams along .text (DualGate starts in gold)",
        )
        written += plot_autocorr(test, "flexo_test_autocorr", "Flexo test.elf: autocorrelation of the replica comb")
        written += plot_periodogram(
            test,
            "flexo_test_periodogram",
            "Flexo test.elf: spatial frequency of DualGate copies",
        )
        written += plot_recurrence(test, "flexo_test_recurrence")
        written += plot_two_family(test, "flexo_test_two_family")
    if sbox:
        written += plot_periodogram(
            sbox,
            "flexo_sbox_periodogram",
            "Flexo sbox: 28 DualGates → one spectral line",
        )
        written += plot_two_family(sbox, "flexo_sbox_two_family")
    if dcache:
        written += plot_two_family(dcache, "flexo_dcache_two_family")
        written += plot_periodogram(
            dcache,
            "flexo_dcache_periodogram",
            "Flexo-DCache test: DualGate period as a spectral line",
        )
    if tlb:
        written += plot_periodogram(
            tlb,
            "flexo_tlb_periodogram",
            "Flexo-TLB test: DualGate period as a spectral line",
        )
    if gitm:
        written += plot_combined(gitm, "gitm_and_combined")
        written += plot_periodogram(
            gitm,
            "gitm_and_periodogram",
            "GITM and_timing: gate copies are a spatial frequency",
        )
        written += plot_autocorr(gitm, "gitm_and_autocorr", "GITM and_timing: autocorrelation of gate spacing")
        written += plot_waveform(gitm, "gitm_and_waveform", "GITM and_timing: replica comb along .text")
        written += plot_two_family(gitm, "gitm_and_two_family")
    if tae:
        written += plot_tae_trap(tae, "tae_jmpreg_trap")
        written += plot_two_family(tae, "tae_two_family")
    if simd and tmpl:
        written += plot_negative_panel(simd, tmpl, "negative_control")
    elif simd:
        written += plot_periodogram(simd, "neg_simd_periodogram", "SIMD negative: one cloned kernel")
    crypto = results.get("neg_crypto")
    if simd and crypto:
        written += plot_negative_panel(simd, crypto, "negative_simd_crypto")

    public = {k: result_public(v) for k, v in results.items()}
    (HERE / "measurements.json").write_text(json.dumps(public, indent=2) + "\n")
    print("measurements", HERE / "measurements.json", flush=True)
    print("figures", len(written), flush=True)


if __name__ == "__main__":
    main()
