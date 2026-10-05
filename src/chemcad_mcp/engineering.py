"""Pure helpers for explicit component mapping and CHP accounting."""

from __future__ import annotations

import math
from datetime import datetime, timedelta


def component_vector(components: list[dict], supplied: dict[str, float]) -> list[float]:
    """Keys are exact names (case insensitive) or CHEMCAD database IDs, never positions."""
    result = [0.0] * len(components)
    assigned = set()
    for key, value in supplied.items():
        matches = [
            i
            for i, c in enumerate(components)
            if str(c["id"]) == str(key) or c["name"].casefold() == str(key).casefold()
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Unknown or ambiguous component {key!r}; use list_components names or database IDs"
            )
        index = matches[0]
        if index in assigned:
            raise ValueError(f"Component supplied more than once: {key}")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Component values must be finite numbers")
        assigned.add(index)
        result[index] = value
    return result


def chp_metrics(
    fuel_heat_input_w: float,
    turbine_shaft_power_w: float,
    compressor_shaft_power_w: float,
    recovered_heat_w: float = 0.0,
    gearbox_efficiency: float = 1.0,
    generator_efficiency: float = 1.0,
    auxiliary_power_w: float = 0.0,
    duct_fuel_heat_input_w: float = 0.0,
) -> dict:
    values = locals().copy()
    for name, value in values.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if not 0 < gearbox_efficiency <= 1 or not 0 < generator_efficiency <= 1:
        raise ValueError("Gearbox and generator efficiencies must be in (0,1]")
    fuel = fuel_heat_input_w + duct_fuel_heat_input_w
    shaft = turbine_shaft_power_w - compressor_shaft_power_w
    electrical = shaft * gearbox_efficiency * generator_efficiency - auxiliary_power_w
    offline = fuel <= 0 or electrical <= 0
    warnings = []
    if offline:
        warnings.append("Offline/invalid operating point: no efficiency calculated")
    elif electrical + recovered_heat_w > fuel:
        warnings.append(
            "Useful output exceeds fuel input: check units, LHV/HHV basis and heat-recovery boundaries"
        )
    return {
        "net_shaft_power_w": shaft,
        "net_electrical_power_w": electrical,
        "total_fuel_heat_input_w": fuel,
        "useful_heat_w": recovered_heat_w,
        "electrical_efficiency": None if offline else electrical / fuel,
        "total_chp_efficiency": None
        if offline
        else (electrical + recovered_heat_w) / fuel,
        "heat_basis": "Caller must use one consistent LHV or HHV basis for ALL fuel inputs",
        "warnings": warnings,
    }


def screen_operating_points(
    points: list[dict],
    excluded_intervals: list[dict] | None = None,
    transient_buffer_minutes: float = 30.0,
) -> dict:
    """Screen supplied observations; never read a workbook or mix turbine IDs."""
    if (
        len(points) > 10000
        or not math.isfinite(transient_buffer_minutes)
        or transient_buffer_minutes < 0
    ):
        raise ValueError(
            "At most 10000 points; transient buffer must be finite/nonnegative"
        )
    intervals = []
    turbine_ids = {
        str(point["turbine_id"])
        for point in points
        if point.get("turbine_id") is not None
    }
    if len(turbine_ids) > 1:
        raise ValueError("Screen one turbine at a time; do not mix turbine IDs")
    buffer = timedelta(minutes=transient_buffer_minutes)
    for interval in excluded_intervals or []:
        start, end = (
            datetime.fromisoformat(interval["start"]),
            datetime.fromisoformat(interval["end"]),
        )
        if end < start:
            raise ValueError("Exclusion interval ends before it starts")
        intervals.append((start, end))
    output = []
    for point in points:
        timestamp = datetime.fromisoformat(point["timestamp"])
        reasons = []
        try:
            for start, end in intervals:
                if start <= timestamp <= end:
                    reasons.append("reported_outage")
                elif start - buffer <= timestamp <= end + buffer:
                    reasons.append("startup_shutdown_buffer")
        except TypeError:
            raise ValueError(
                "Timestamps and intervals must consistently include or omit timezone offsets"
            ) from None
        power, fuel = point.get("electrical_power_kw"), point.get("fuel_heat_input_kw")
        valid = all(
            not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
            for v in (power, fuel)
        )
        if not valid:
            reasons.append("missing_or_invalid_power_fuel")
        elif power <= 0 or fuel <= 0:
            reasons.append("offline_or_nonpositive_power_fuel")
        elif power > fuel:
            reasons.append("electrical_efficiency_above_one")
        output.append(
            {
                "timestamp": point["timestamp"],
                "eligible": not reasons,
                "reasons": sorted(set(reasons)),
                "electrical_efficiency": power / fuel if not reasons else None,
            }
        )
    return {
        "points": output,
        "eligible_count": sum(p["eligible"] for p in output),
        "warning": "Passing this screen does not prove steady state; verify stable load, sensor validity, fuel-flow units and timestamp alignment separately.",
    }
