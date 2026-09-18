"""Call a running API with ALL public inputs; never supplies expected answers to it."""
import argparse
import json
import math
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from gridwise.validation import validate_request, validate_directives, require
from gridwise.replay import replay


def check_interpretation(actual, expected):
    for a, e in zip(actual, expected):
        for key in ["note_index", "applies", "directive_type"]:
            require(a[key] == e[key], "Incorrect interpreted field: " + key)
        aa, ea = a["structured_adjustment"], e["structured_adjustment"]
        if ea is None:
            require(aa is None, "Expected no_op")
            continue
        require(aa["hours"] == ea["hours"], "Incorrect interpreted hours")
        for key in ea:
            if key != "hours":
                require(abs(aa[key] - ea[key]) <= 0.01, "Incorrect interpreted number")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    cases = json.loads((pathlib.Path(__file__).resolve().parents[1] / "data/public_samples.json").read_text())["cases"]
    failures = 0
    timings = []
    with urllib.request.urlopen(args.url.rstrip("/") + "/health", timeout=5) as response:
        require(json.load(response) == {"status": "ok"}, "Health check failed")
    for _ in range(args.repeat):
        for case in cases:
            start = time.monotonic()
            try:
                request = urllib.request.Request(args.url.rstrip("/") + "/optimize-energy", data=json.dumps(case["input"]).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    output = json.load(response)
                data = validate_request(case["input"])
                truth = case["expected_output"]["directive_interpretation"]
                validate_directives(data, output["directive_interpretation"])
                check_interpretation(output["directive_interpretation"], truth)
                # Ground truth, NOT the service's own interpretation, validates the plan.
                replay(data, output, truth, tolerance=0.01)
                require(abs(output["total_cost_bdt"] - case["expected_output"]["total_cost_bdt"]) <= 0.01, "Cost differs from public optimum")
                label = "PASS"
            except Exception:
                failures += 1
                label = "FAIL (check interpretation, validity, model configuration, or availability)"
            elapsed = time.monotonic() - start
            timings.append(elapsed)
            print(f"{case['id']} {label}; {elapsed:.2f}s")
    p95 = sorted(timings)[math.ceil(0.95 * len(timings)) - 1]
    print(f"{len(timings)-failures}/{len(timings)} passed; observed sequential p95: {p95:.2f}s")
    print("Public-case evidence only; this does not establish hidden-case accuracy or load performance.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
