"""96-variable linear program with one signed battery flow per hour."""
import threading
import numpy as np
from scipy.optimize import linprog
from .validation import effective_limits
from .replay import replay

SOLVER_LOCK = threading.Lock()


class OptimizationError(RuntimeError):
    pass


def optimize(data, directives):
    solar, reserve, charge, discharge, grid = effective_limits(data, directives)
    battery = data["battery"]
    # Four variables per hour: grid purchase, solar used, signed charge, energy after.
    cost = np.zeros(96)
    equality = np.zeros((49, 96))
    rhs = np.zeros(49)
    bounds = []
    for h, item in enumerate(data["hours"]):
        g, s, q, e = range(4 * h, 4 * h + 4)
        cost[g] = item["tariff_bdt_per_kwh"]
        bounds.extend([(0, grid[h]), (0, solar[h]), (-discharge[h], charge[h]), (reserve[h], battery["capacity_kwh"])])
        # g + s - q = demand. q > 0 charges; q < 0 discharges.
        equality[h, [g, s, q]] = [1, 1, -1]
        rhs[h] = item["demand_kwh"]
        # E_after - q = E_before.
        equality[24 + h, [e, q]] = [1, -1]
        if h == 0:
            rhs[24 + h] = battery["initial_energy_kwh"]
        else:
            equality[24 + h, e - 4] = -1
    equality[48, 95] = 1
    rhs[48] = battery["initial_energy_kwh"]
    with SOLVER_LOCK:
        result = linprog(cost, A_eq=equality, b_eq=rhs, bounds=bounds, method="highs", options={"time_limit": 3.0})
    if not result.success:
        raise OptimizationError("No verified optimum available")
    plan = []
    for h in range(24):
        g, s, q, e = [float(v) for v in result.x[4*h:4*h+4]]
        if abs(q) < 1e-9:
            q = 0.0
        plan.append({"hour": h, "grid_kwh": max(0.0, g), "solar_used_kwh": max(0.0, s),
                     "battery_action": "charge" if q > 0 else "discharge" if q < 0 else "idle",
                     "battery_kwh": abs(q), "battery_energy_after_kwh": max(0.0, e)})
    response = {
        "scenario_id": data["scenario_id"], "directive_interpretation": directives,
        "hourly_plan": plan, "total_grid_kwh": sum(p["grid_kwh"] for p in plan),
        "total_cost_bdt": sum(p["grid_kwh"] * data["hours"][h]["tariff_bdt_per_kwh"] for h, p in enumerate(plan)),
        "peak_grid_kwh": max(p["grid_kwh"] for p in plan),
        "plan_summary": "Minimum-cost linear-program schedule under validated operator directives; battery returns to its starting energy."
    }
    replay(data, response, directives)
    return response
