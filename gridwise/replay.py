"""Replay returned numbers independently of the solver and its model matrix."""
from .validation import require, nonnegative, keys, validate_directives


def replay(data, output, ground_truth, tolerance=0.00001):
    validate_directives(data, ground_truth)
    keys(output, ["scenario_id", "directive_interpretation", "hourly_plan", "total_grid_kwh", "total_cost_bdt", "peak_grid_kwh", "plan_summary"])
    validate_directives(data, output["directive_interpretation"])
    require(output["scenario_id"] == data["scenario_id"], "Scenario mismatch")
    require(type(output["plan_summary"]) is str and bool(output["plan_summary"]), "Missing summary")
    plan = output["hourly_plan"]
    require(type(plan) is list and len(plan) == 24, "Invalid plan length")
    battery = data["battery"]
    energy = battery["initial_energy_kwh"]
    cost = total_grid = peak = 0.0
    for h, p in enumerate(plan):
        keys(p, ["hour", "grid_kwh", "solar_used_kwh", "battery_action", "battery_kwh", "battery_energy_after_kwh"])
        require(type(p["hour"]) is int and p["hour"] == h, "Invalid plan hours")
        require(all(nonnegative(p[k]) for k in ("grid_kwh", "solar_used_kwh", "battery_kwh", "battery_energy_after_kwh")), "Invalid plan number")
        action = p["battery_action"]
        require(action in ("idle", "charge", "discharge"), "Invalid battery action")
        amount = p["battery_kwh"]
        require(action != "idle" or amount == 0, "Idle has nonzero flow")
        charge = amount if action == "charge" else 0
        discharge = amount if action == "discharge" else 0
        require(charge <= battery["max_charge_kwh_per_hour"] + tolerance, "Charge rate exceeded")
        require(discharge <= battery["max_discharge_kwh_per_hour"] + tolerance, "Discharge rate exceeded")
        solar = data["hours"][h]["solar_kwh"]
        reserve = battery["minimum_energy_kwh"]
        cap = float("inf")
        for d in ground_truth:
            a = d["structured_adjustment"]
            if a is None or h not in a["hours"]:
                continue
            kind = d["directive_type"]
            if kind == "solar_reduction":
                solar = data["hours"][h]["solar_kwh"] * a["factor"]
            elif kind == "minimum_battery_reserve":
                reserve = max(reserve, a["minimum_energy_kwh"])
            elif kind == "max_grid_window":
                cap = min(cap, a["max_grid_kwh"])
            elif kind == "no_charge_window":
                require(charge <= tolerance, "Charging prohibited")
            elif kind == "no_discharge_window":
                require(discharge <= tolerance, "Discharging prohibited")
        require(p["grid_kwh"] <= cap + tolerance, "Grid cap exceeded")
        require(p["solar_used_kwh"] <= solar + tolerance, "Solar overuse")
        require(abs(p["grid_kwh"] + p["solar_used_kwh"] + discharge - data["hours"][h]["demand_kwh"] - charge) <= tolerance, "Energy balance failed")
        energy += charge - discharge
        require(abs(energy - p["battery_energy_after_kwh"]) <= tolerance, "State transition failed")
        require(reserve - tolerance <= energy <= battery["capacity_kwh"] + tolerance, "Reserve or capacity violated")
        total_grid += p["grid_kwh"]
        cost += p["grid_kwh"] * data["hours"][h]["tariff_bdt_per_kwh"]
        peak = max(peak, p["grid_kwh"])
    require(abs(energy - battery["initial_energy_kwh"]) <= tolerance, "Final neutrality failed")
    for name, value in [("total_cost_bdt", cost), ("total_grid_kwh", total_grid), ("peak_grid_kwh", peak)]:
        require(nonnegative(output[name]) and abs(output[name] - value) <= tolerance, "Incorrect total")
