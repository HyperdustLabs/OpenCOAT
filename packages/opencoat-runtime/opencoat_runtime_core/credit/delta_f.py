"""ΔF free-energy gate for plasticity rewrites (morphogenetic §5)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DeltaFResult:
    delta_error: float
    delta_complexity: float
    delta_f: float
    accept: bool
    acceptance_rate: float


def complexity_l_pi(*, partition_bits: float, node_bits: float, synapse_bits: float) -> float:
    """``ΔComplexity = L(π) + L(节点) + L(突触)`` (tier-1 proxy, bits)."""
    return partition_bits + node_bits + synapse_bits


def delta_error_tier1(*, separability_gain: float, eta: float = 1.0) -> float:
    """``ΔError ≈ −η·G(a)`` — negative when split reduces variance."""
    return -eta * separability_gain


def evaluate_delta_f(
    *,
    separability_gain: float,
    partition_bits: float = 2.0,
    node_bits: float = 4.0,
    synapse_bits: float = 2.0,
    beta: float = 0.5,
    temperature: float = 1.0,
    eta: float = 1.0,
) -> DeltaFResult:
    d_err = delta_error_tier1(separability_gain=separability_gain, eta=eta)
    d_cplx = complexity_l_pi(
        partition_bits=partition_bits,
        node_bits=node_bits,
        synapse_bits=synapse_bits,
    )
    delta_f = d_err + beta * d_cplx
    rate = min(1.0, math.exp(-delta_f / max(temperature, 1e-6)))
    return DeltaFResult(
        delta_error=d_err,
        delta_complexity=d_cplx,
        delta_f=delta_f,
        accept=delta_f < 0.0,
        acceptance_rate=rate,
    )


__all__ = [
    "DeltaFResult",
    "complexity_l_pi",
    "delta_error_tier1",
    "evaluate_delta_f",
]
