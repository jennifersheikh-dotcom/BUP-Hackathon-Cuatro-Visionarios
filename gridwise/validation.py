"""Strict validation of input and untrusted model output."""
import json
import math


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def nonnegative(value):
    return number(value) and value >= 0


def keys(obj, expected):
    require(type(obj) is dict and set(obj) == set(expected), "Unexpected object fields")


def load_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def bad_constant(_):
        raise Invalid("Non-finite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise Invalid("Invalid JSON") from exc


def validate_request(data):
    keys(data, ["scenario_id", "operator_notes", "hours", "battery"])
    require(type(data["scenario_id"]) is str and bool(data["scenario_id"].strip()), "Invalid scenario_id")
    notes = data["operator_notes"]
    require(type(notes) is list and 1 <= len(notes) <= 3, "Expected 1-3 notes")
    require(all(type(n) is str and bool(n.strip()) for n in notes), "Empty or invalid note")
    hours = data["hours"]
    require(type(hours) is list and len(hours) == 24, "Expected 24 hours")
    seen = set()
    for h in hours:
        keys(h, ["hour", "demand_kwh", "solar_kwh", "tariff_bdt_per_kwh"])
        require(type(h["hour"]) is int and 0 <= h["hour"] <= 23, "Invalid hour")
        require(h["hour"] not in seen, "Duplicate hour")
        seen.add(h["hour"])
        require(all(nonnegative(h[k]) for k in ("demand_kwh", "solar_kwh", "tariff_bdt_per_kwh")), "Invalid hourly number")
    b = data["battery"]
    keys(b, ["capacity_kwh", "initial_energy_kwh", "minimum_energy_kwh", "max_charge_kwh_per_hour", "max_discharge_kwh_per_hour"])
    require(all(nonnegative(v) for v in b.values()), "Invalid battery number")
    require(b["minimum_energy_kwh"] <= b["initial_energy_kwh"] <= b["capacity_kwh"], "Invalid battery bounds")
    return {**data, "hours": sorted(hours, key=lambda h: h["hour"])}


ADJUSTMENTS = {
    "solar_reduction": "factor",
    "minimum_battery_reserve": "minimum_energy_kwh",
    "max_grid_window": "max_grid_kwh",
    "no_charge_window": None,
    "no_discharge_window": None,
}


def validate_directives(data, entries):
    require(type(entries) is list and len(entries) == len(data["operator_notes"]), "Missing directive")
    for index, item in enumerate(entries):
        keys(item, ["note_index", "applies", "directive_type", "structured_adjustment", "explanation"])
        require(type(item["note_index"]) is int and item["note_index"] == index, "Invalid note mapping")
        require(type(item["explanation"]) is str and bool(item["explanation"].strip()), "Missing explanation")
        kind = item["directive_type"]
        require(type(kind) is str, "Invalid directive type")
        adj = item["structured_adjustment"]
        if kind == "no_op":
            require(item["applies"] is False and adj is None, "Invalid no_op")
            continue
        require(kind in ADJUSTMENTS and item["applies"] is True, "Unsupported directive or applies")
        numeric_key = ADJUSTMENTS[kind]
        keys(adj, ["hours"] + ([numeric_key] if numeric_key else []))
        hours = adj["hours"]
        require(type(hours) is list and bool(hours), "Missing directive hours")
        require(all(type(h) is int and 0 <= h <= 23 for h in hours), "Invalid directive hour")
        require(hours == sorted(set(hours)), "Hours must be unique and sorted")
        if numeric_key:
            value = adj[numeric_key]
            require(nonnegative(value), "Invalid directive number")
            if kind == "solar_reduction":
                require(value <= 1, "Solar factor exceeds one")
            if kind == "minimum_battery_reserve":
                require(value <= data["battery"]["capacity_kwh"], "Reserve exceeds capacity")
    return entries


def effective_limits(data, entries):
    """Combine hard limits; reject conflicting solar fractions (unspecified by pack)."""
    b = data["battery"]
    solar = [h["solar_kwh"] for h in data["hours"]]
    reserve = [b["minimum_energy_kwh"]] * 24
    charge = [b["max_charge_kwh_per_hour"]] * 24
    discharge = [b["max_discharge_kwh_per_hour"]] * 24
    grid = [None] * 24
    factors = {}
    for item in entries:
        kind = item["directive_type"]
        if kind == "no_op":
            continue
        adj = item["structured_adjustment"]
        for h in adj["hours"]:
            if kind == "solar_reduction":
                factor = adj["factor"]
                require(h not in factors or factors[h] == factor, "Conflicting solar factors: organizer clarification required")
                factors[h] = factor
                solar[h] = data["hours"][h]["solar_kwh"] * factor
            elif kind == "minimum_battery_reserve":
                reserve[h] = max(reserve[h], adj["minimum_energy_kwh"])
            elif kind == "no_charge_window":
                charge[h] = 0
            elif kind == "no_discharge_window":
                discharge[h] = 0
            elif kind == "max_grid_window":
                grid[h] = adj["max_grid_kwh"] if grid[h] is None else min(grid[h], adj["max_grid_kwh"])
    return solar, reserve, charge, discharge, grid
