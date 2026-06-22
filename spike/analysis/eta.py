"""Projeção de ETA: integra comprimento/velocidade ao longo dos segmentos."""

from __future__ import annotations

from analysis.speed_field import SpeedField


def project_travel_time(
    field: SpeedField, s0: float, t0_epoch: float, s_target: float
) -> float:
    """Tempo de viagem previsto (s) de s0 a s_target, usando as velocidades de
    segmento congeladas em t0. Caminha segmento a segmento, usando só o trecho
    que cai dentro de [s0, s_target]."""
    if s_target <= s0:
        return 0.0
    seg_m = field.segment_m
    total = 0.0
    s = s0
    while s < s_target:
        seg_end = (int(s // seg_m) + 1) * seg_m
        step_end = min(seg_end, s_target)
        length = step_end - s
        v = field.speed(s, t0_epoch)
        total += length / v
        s = step_end
    return total
