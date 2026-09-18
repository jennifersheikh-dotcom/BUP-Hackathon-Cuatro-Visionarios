import copy
import json
import pathlib
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from gridwise.llm import Interpreter, ModelError
from gridwise.validation import validate_request, validate_directives, load_json, Invalid
from gridwise.optimizer import optimize
from gridwise.replay import replay
from gridwise.server import make_handler

CASES = json.loads((pathlib.Path(__file__).resolve().parents[1] / "data/public_samples.json").read_text())["cases"]


class TestOptimizer(unittest.TestCase):
    def test_all_ten_public_optima_with_supplied_ground_truth(self):
        # Deliberately bypasses the model ONLY in this offline optimizer unit test.
        for case in CASES:
            with self.subTest(case=case["id"]):
                data = validate_request(case["input"])
                truth = validate_directives(data, case["expected_output"]["directive_interpretation"])
                out = optimize(data, truth)
                replay(data, out, truth)
                self.assertAlmostEqual(out["total_cost_bdt"], case["expected_output"]["total_cost_bdt"], delta=0.01)

    def test_replay_detects_corruption(self):
        case = CASES[0]
        data = validate_request(case["input"])
        truth = case["expected_output"]["directive_interpretation"]
        output = optimize(data, truth)
        for field in ["grid_kwh", "solar_used_kwh", "battery_energy_after_kwh"]:
            broken = copy.deepcopy(output)
            broken["hourly_plan"][0][field] += 2
            with self.subTest(field=field), self.assertRaises(Invalid):
                replay(data, broken, truth)
        output["total_cost_bdt"] += 2
        with self.assertRaises(Invalid):
            replay(data, output, truth)

    def test_zero_capacity_and_surplus_solar(self):
        data = copy.deepcopy(CASES[0]["input"])
        data["operator_notes"] = ["A club event is scheduled next month."]
        for k in data["battery"]:
            data["battery"][k] = 0
        for h in data["hours"]:
            h["solar_kwh"] = h["demand_kwh"] + 100
        truth = [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "Unrelated."}]
        output = optimize(validate_request(data), truth)
        self.assertEqual(output["total_cost_bdt"], 0)
        self.assertTrue(all(p["battery_action"] == "idle" for p in output["hourly_plan"]))


class TestGuardrails(unittest.TestCase):
    def test_invalid_inputs(self):
        for bad_value in [float("nan"), float("inf"), True, -1, "100"]:
            data = copy.deepcopy(CASES[0]["input"])
            data["hours"][0]["demand_kwh"] = bad_value
            with self.subTest(value=bad_value), self.assertRaises(Invalid):
                validate_request(data)
        data = copy.deepcopy(CASES[0]["input"])
        data["hours"][1]["hour"] = 0
        with self.assertRaises(Invalid):
            validate_request(data)

    def test_invalid_model_output(self):
        data = validate_request(CASES[0]["input"])
        good = CASES[0]["expected_output"]["directive_interpretation"]
        variants = []
        for field, value in [("applies", False), ("directive_type", "change_tariff"), ("note_index", True)]:
            x = copy.deepcopy(good)
            x[0][field] = value
            variants.append(x)
        for hours in [[13, 12], [12, 12], [24], [True], []]:
            x = copy.deepcopy(good)
            x[0]["structured_adjustment"]["hours"] = hours
            variants.append(x)
        for factor in [-0.1, 1.1, float("nan"), True]:
            x = copy.deepcopy(good)
            x[0]["structured_adjustment"]["factor"] = factor
            variants.append(x)
        variants.extend([good[:1], list(reversed(good))])
        x = copy.deepcopy(good)
        x[1]["structured_adjustment"] = {}
        variants.append(x)
        for x in variants:
            with self.subTest(output=x), self.assertRaises(Invalid):
                validate_directives(data, x)

    def test_duplicate_and_nonfinite_json(self):
        for raw in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{broken']:
            with self.assertRaises(Invalid):
                load_json(raw)


class TestHTTP(unittest.TestCase):
    def setUp(self):
        class TestOnlyInterpreter:
            def interpret(self, data):
                if data["scenario_id"] == "FAIL-PROVIDER":
                    raise RuntimeError("FAKE_SECRET_DO_NOT_RETURN")
                return CASES[0]["expected_output"]["directive_interpretation"]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(TestOnlyInterpreter()))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, raw):
        request = urllib.request.Request(self.url + "/optimize-energy", data=raw, headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_health(self):
        with urllib.request.urlopen(self.url + "/health") as response:
            self.assertEqual(json.load(response), {"status": "ok"})

    def test_request_reaches_interpreter_optimizer_and_replay(self):
        status, output = self.post(json.dumps(CASES[0]["input"]).encode())
        self.assertEqual(status, 200)
        replay(validate_request(CASES[0]["input"]), output, CASES[0]["expected_output"]["directive_interpretation"])

    def test_malformed_json(self):
        status, _ = self.post(b'{bad')
        self.assertEqual(status, 400)

    def test_provider_failure_is_controlled_and_has_no_fallback(self):
        data = copy.deepcopy(CASES[0]["input"])
        data["scenario_id"] = "FAIL-PROVIDER"
        status, output = self.post(json.dumps(data).encode())
        self.assertEqual(status, 500)
        self.assertNotIn("FAKE_SECRET", json.dumps(output))
        self.assertNotIn("hourly_plan", output)


class TestModelAdapter(unittest.TestCase):
    def test_chat_transport_and_guardrails_with_simulated_provider(self):
        payloads = []
        replies = [CASES[0]["expected_output"]["directive_interpretation"], []]

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payloads.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                content = json.dumps({"directive_interpretation": replies.pop(0)})
                body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict("os.environ", {"LLM_CHAT_URL": f"http://127.0.0.1:{server.server_port}/v1/chat/completions", "LLM_MODEL": "simulated-provider", "LLM_API_KEY": ""}):
                interpreter = Interpreter()
                data = validate_request(CASES[0]["input"])
                result = interpreter.interpret(data)
                self.assertEqual(result, CASES[0]["expected_output"]["directive_interpretation"])
                self.assertEqual(payloads[0]["model"], "simulated-provider")
                sent = json.loads(payloads[0]["messages"][1]["content"])
                self.assertEqual(sent["operator_notes"], data["operator_notes"])
                self.assertNotIn("expected_output", sent)
                with self.assertRaises(ModelError):
                    interpreter.interpret(data)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
