"""RACH-lite: random access to a cell and the handover gap, for an emulation step of tenths of a second.

Each access is a sequence of preamble attempts (TS 38.321 5.1): open-loop preamble power with ramping
(TS 38.213 7.4), detection by the gNB as a function of the preamble SNR (TS 38.104 8.4), the random access
response on the downlink, and contention with other UEs that picked the same preamble in the same occasion.
The access fails when preambleTransMax attempts are used or T304 expires. A successful handover costs the
RRC procedure delay plus the TS 38.133 6.1.1.2 interruption T_search + T_IU + 20 ms + T_delta, where T_IU
is the time spent in random access.

Status of each value: CONFIG (a network setting), DERIVED, ASSUMPTION or UNVERIFIED (not checked in the spec).
"""
import math
from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class AccessConfig:
    # Preamble detection: probability 99 % at this SNR. TS 38.104 8.4.1.5, format 0, 2 Rx, TDLC300-100. UNVERIFIED.
    prach_snr_99_db: float = -6.0
    # Width of the logistic detection curve around that point. ASSUMPTION.
    prach_slope_db: float = 1.0
    # Format 0 preamble: 839 subcarriers of 1.25 kHz (TS 38.211 6.3.3.1). DERIVED.
    prach_bandwidth_hz: float = 839 * 1250.0
    # preambleReceivedTargetPower (TS 38.331 RACH-ConfigGeneric). CONFIG.
    preamble_target_dbm: float = -100.0
    # powerRampingStep, dB2. CONFIG.
    ramping_step_db: float = 2.0
    # preambleTransMax, n10. CONFIG.
    preamble_trans_max: int = 10
    # Period between PRACH occasions. CONFIG.
    prach_period_ms: float = 10.0
    # ra-ResponseWindow, sl10 at 30 kHz. CONFIG.
    rar_window_ms: float = 5.0
    # ra-ContentionResolutionTimer, sf64. CONFIG.
    contention_resolution_ms: float = 64.0
    # Backoff after a collision, uniform in [0, backoff_ms]; 0 = no backoff indicator. CONFIG.
    backoff_ms: float = 0.0
    # Contention-based preambles per occasion (of 64). CONFIG.
    contention_preambles: int = 52
    # Accesses per second per cell from UEs that are not emulated. ASSUMPTION.
    background_access_hz: float = 5.0
    # Contention also on handover (a dedicated preamble would avoid it). CONFIG.
    contention_on_handover: bool = True
    # T304 bounds the access of a handover. CONFIG.
    t304_ms: float = 1000.0
    # RRC procedure delay of RRCReconfiguration (TS 38.331 12). UNVERIFIED.
    rrc_delay_ms: float = 10.0
    # TS 38.133 6.1.1.2: T_search (0 for a known cell), fixed 20 ms, T_delta (one SSB period).
    t_search_ms: float = 0.0
    processing_ms: float = 20.0
    ssb_period_ms: float = 20.0
    # Downlink SINR below which the random access response is not decoded (Qout, about -8 dB). ASSUMPTION.
    rar_sinr_min_db: float = -8.0
    seed: int = 1

    @classmethod
    def from_dict(cls, d):
        known = set(asdict(cls()))
        bad = set(d or {}) - known
        if bad:
            raise ValueError(f"unknown access settings: {sorted(bad)}")
        return cls(**(d or {}))


class AccessModel:
    """Random access of one UE to one cell. The link budget comes from the emulator's LinkConfig."""

    def __init__(self, cfg, link_config):
        self.cfg = cfg
        self.pcmax = link_config.ue_power_dbm
        self.noise = -174.0 + 10 * math.log10(cfg.prach_bandwidth_hz) + link_config.bs_noise_figure_db
        self.ul_margin = link_config.uplink_interference_margin_db
        self.rng = np.random.default_rng(cfg.seed)
        # logistic with P(snr_99) = 0.99
        self.mid = cfg.prach_snr_99_db - cfg.prach_slope_db * math.log(99.0)

    def detection_probability(self, snr_db):
        return 1.0 / (1.0 + math.exp(-(snr_db - self.mid) / self.cfg.prach_slope_db))

    def preamble_snr(self, path_gain_db, attempt):
        """Preamble SNR at the gNB on attempt 0, 1, ...: open-loop power with ramping, capped at Pcmax."""
        pl = -path_gain_db
        p = min(self.pcmax, self.cfg.preamble_target_dbm + pl + attempt * self.cfg.ramping_step_db)
        return p - pl - self.noise - self.ul_margin

    def access(self, path_gain_db, dl_sinr_db, others=0, step_s=0.5, handover=True):
        """One access. others = emulated UEs accessing the same cell in the same step.
        Returns dict(ok, time_ms, attempts, cause, collisions); cause is None on success."""
        c, rng = self.cfg, self.rng
        limit = c.t304_ms if handover else math.inf
        t = rng.uniform(0, c.prach_period_ms)
        same_occasion = min(1.0, c.prach_period_ms / (1000.0 * step_s))
        contention = c.contention_on_handover or not handover
        cause, collisions = None, 0
        for k in range(c.preamble_trans_max):
            if t > limit:
                cause = "t304"
                break
            detected = rng.random() < self.detection_probability(self.preamble_snr(path_gain_db, k))
            if not detected or dl_sinr_db < c.rar_sinr_min_db:
                cause = "detection" if not detected else "rar"
                t += c.rar_window_ms + rng.uniform(0, c.prach_period_ms)
                continue
            if contention:
                n = rng.poisson(c.background_access_hz * c.prach_period_ms / 1000.0) + rng.binomial(others, same_occasion)
                if n and rng.random() < 1.0 - (1.0 - 1.0 / c.contention_preambles) ** n:
                    cause, collisions = "collision", collisions + 1
                    t += c.rar_window_ms + c.contention_resolution_ms + rng.uniform(0, c.backoff_ms) + rng.uniform(0, c.prach_period_ms)
                    continue
            t += c.rar_window_ms
            if t > limit:
                cause = "t304"
                break
            return dict(ok=True, time_ms=t, attempts=k + 1, cause=None, collisions=collisions)
        return dict(ok=False, time_ms=min(t, limit), attempts=k + 1, cause=cause or "attempts", collisions=collisions)

    def handover_gap_ms(self, access_ms):
        """Data gap of a successful handover: RRC procedure delay + T_search + T_IU + 20 ms + T_delta."""
        c = self.cfg
        return c.rrc_delay_ms + c.t_search_ms + access_ms + c.processing_ms + c.ssb_period_ms
