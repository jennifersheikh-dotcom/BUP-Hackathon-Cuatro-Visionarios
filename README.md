# GridWise — Smart Campus Energy Optimization

BUP CSE Fest 2026 Hackathon submission for the LLM-assisted GridWise preliminary. The service interprets campus energy operator notes with a real generative model, validates the extracted directives, and solves a 24-hour minimum-cost energy schedule. It exposes `GET /health` and `POST /optimize-energy` per the Problem Statement contract.

**Status:** offline test suite passing locally (see `VERIFICATION.md`); not yet deployed, containerized, or tested against a live LLM. See [Remaining work before submission](#remaining-work-before-submission).

## Development notes

Per Participant Guide §04, AI coding assistants are permitted, but the team is responsible for the core architecture and logic and must credit AI assistance and dependencies honestly (see [Credits](#credits)). `TEAM_DECISIONS.md` is the team's own worksheet for the design decisions, provider choice, and contribution notes this README does not speak for — fill it out with real answers before submitting, not generated ones.

Repository policy: create the repository after question reveal, keep it private during the event, and make it public only after the submission deadline. Use only the synthetic challenge data supplied by the harness — the samples in `data/` are unmodified except filename.

## Files to understand first

| File | Purpose |
|---|---|
| `gridwise/llm.py` | Genuine model call, constrained interpretation prompt, JSON parsing |
| `gridwise/validation.py` | Request checks, directive guardrails, effective operating limits |
| `gridwise/optimizer.py` | Linear program and conversion to the required schedule |
| `gridwise/replay.py` | Independent hour-by-hour checks of returned values |
| `gridwise/server.py` | Required HTTP routes and controlled errors |
| `tests/test_project.py` | Offline tests; model fixtures are confined to tests |
| `scripts/test_live.py` | Real API evaluation on public inputs and reference semantics |
| `TEAM_DECISIONS.md` | Decisions the team must genuinely make and explain |

## Architecture

1. The API validates a scenario with 24 hours and 1–3 notes.
2. The configured language model receives the notes and battery capacity. It returns exactly one structured interpretation per note.
3. Deterministic guardrails reject unsupported types, invalid hours, invalid numeric values, incorrect note mappings, and incorrect `applies` semantics.
4. Valid directives modify solar availability, reserve levels, charge/discharge availability, and grid limits.
5. SciPy's HiGHS linear-program solver minimizes total grid electricity cost.
6. A separate replay checker recomputes balance, state transitions, constraints, and totals before an answer is returned.

The model does not produce the final energy schedule. There is no phrase-matching interpreter, sample-case lookup, or hidden fallback that bypasses the language model. Public reference interpretations are used only by offline tests; the Docker image does not include them. If the model fails or returns invalid data, the service returns a controlled HTTP 500 and no schedule. It never marks all notes as irrelevant to conceal model failure.

## Local quickstart (Python 3.12)

Clone the repository and enter its directory.

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
cp .env.example .env
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
Copy-Item .env.example .env
```

`.env.example` is a template that lists only the variable names. Your real `.env` is ignored by Git, so it stays on your machine. Edit `.env` locally with your real model configuration (see [Model configuration](#model-configuration)). Keep it secret, and never put a real API key in `.env.example`, this README, the Dockerfile, or a video. Use shell-safe quoted values if they contain special characters. Load only a file you control.

Load `.env` and start the service:

**Linux / macOS:**

```bash
set -a
source .env
set +a
python -m gridwise.server
```

**Windows (PowerShell):**

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2].Trim().Trim("'").Trim('"')
    }
}
python -m gridwise.server
```

Do not paste key values into a video, public terminal transcript, or chat.

In another terminal:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/optimize-energy \
  -H 'Content-Type: application/json' \
  --data-binary @data/sample_request.json
python scripts/test_live.py --url http://127.0.0.1:8000
```

The health result is `{"status":"ok"}`. A successful optimization response has `scenario_id`, `directive_interpretation`, `hourly_plan` (24 entries), `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, and `plan_summary`. Full example input/output pairs are in `data/public_samples.json`. Equivalent optimal schedules can differ from its reference actions.

## Model configuration

| Variable | Required | Meaning |
|---|---|---|
| `LLM_CHAT_URL` | Yes | Complete endpoint accepting the chat-completions contract below; HTTPS for external hosts |
| `LLM_MODEL` | Yes | Actual provider model name or local model identifier |
| `LLM_API_KEY` | For external hosts | Runtime bearer token; never stored in image/source |
| `PORT` | No | HTTP port, default `8000` |

This adapter requires a provider endpoint that accepts `{model, messages, response_format:{type:"json_object"}}` and returns generated JSON text in `choices[0].message.content`. It uses Python's standard HTTP client, not a provider SDK. A provider using another contract requires an adapter change. Local plain HTTP is permitted only for localhost, loopback, or `host.docker.internal`; external endpoints must use HTTPS. Redirects are rejected to avoid forwarding credentials elsewhere. The guide allows both hosted and local generative models.

**Provider/model: not yet selected.** `LLM_CHAT_URL`, `LLM_MODEL`, and `LLM_API_KEY` are placeholders in `.env.example` until the team picks and configures a real provider. This paragraph must be replaced with the actual provider, exact model identifier, and whether it is hosted or local before submission. Confirm quota and availability through the judging window. A successful health response confirms the local process and startup configuration; it does not prove provider credentials/quota are valid. Run a real optimization request as the end-to-end readiness test.

## Optimization explained

For each hour h, the model has four continuous variables:

- g[h]: non-negative grid energy.
- s[h]: used solar, between zero and effective solar.
- q[h]: signed battery energy flow. Positive charges, negative discharges.
- E[h]: stored energy immediately after the hour.

Minimize `sum(g[h] * tariff[h])`, subject to:

```text
g[h] + s[h] - q[h] = demand[h]
E[h] = E[h-1] + q[h]          (hour 0 uses initial energy)
-available_discharge[h] <= q[h] <= available_charge[h]
active_reserve[h] <= E[h] <= capacity
0 <= g[h] <= active_grid_cap[h] (if there is a cap)
0 <= s[h] <= effective_solar[h]
E[23] = initial_energy
```

This is a 96-variable linear program with 49 equalities. One signed battery variable represents the three allowed actions without simultaneous charge and discharge. This is exact for the supplied ideal battery model with no efficiency loss or export. Adding real-world battery inefficiency would require revisiting the formulation. Ending at the initial energy prevents treating the starting battery as free electricity.

The returned action is `charge` when q is positive, `discharge` when negative, and `idle` when zero. The magnitude is `abs(q)`. Values are not rounded to two decimals before checking; that could break energy balance. The solver must report an optimum, and replay must succeed.

## Tests and verified results

Run offline tests without model credentials:

```bash
python -m unittest discover -s tests -v
```

The ten public scenarios are solved using their supplied ground-truth interpretations in an explicitly isolated optimizer test. Each cost matched its reference optimum within 0.01 BDT. Additional tests cover bad JSON, guardrails, replay corruption, zero-capacity batteries, surplus solar, HTTP behavior, and controlled provider failure. See `VERIFICATION.md` for actual executed results.

**Offline tests do not verify natural-language interpretation.** The HTTP fixture used in unit tests is not a language model and is not available as a runtime mode. Run the live test against your configured model-backed server:

```bash
python scripts/test_live.py --url http://127.0.0.1:8000 --repeat 3
```

This sends only each public `input` to the service, compares semantic interpretations, independently replays the plan against organizer reference directives, and checks cost. It reports pass counts and observed sequential p95. Expected success is 30/30; this has not been achieved or claimed here because no real model was configured. Paraphrase accuracy and concurrent load still need the team's own testing; public examples are not the hidden set.

## Docker fallback and deployment

The Dockerfile is provided but has not yet been built/tested (no Docker daemon in the development sandbox used so far). Build it, test it, and publish an exact image reference in the team's authorized event workflow:

```bash
docker build -t gridwise:reference-v1 .
docker run --rm -d --name gridwise-test --env-file .env -p 8000:8000 gridwise:reference-v1
curl http://127.0.0.1:8000/health
python scripts/test_live.py --url http://127.0.0.1:8000
docker stop gridwise-test
```

For a local model, `localhost` inside a container refers to the container. Configure a reachable model URL; Linux Docker may require `--add-host=host.docker.internal:host-gateway` for a host-based local model.

Use an actual registry you control. Example commands below contain placeholders and are not submitted artifacts:

```bash
docker tag gridwise:reference-v1 YOUR_REGISTRY/YOUR_NAMESPACE/gridwise:EVENT_EXACT_TAG
docker push YOUR_REGISTRY/YOUR_NAMESPACE/gridwise:EVENT_EXACT_TAG
docker pull YOUR_REGISTRY/YOUR_NAMESPACE/gridwise:EVENT_EXACT_TAG
docker run --rm --env-file .env -p 8000:8000 YOUR_REGISTRY/YOUR_NAMESPACE/gridwise:EVENT_EXACT_TAG
```

Replace placeholders with the published tag or digest and include one verified pull/run command in the submission. Keep the image pullable for organizers. Do not publish early if that exposes round code contrary to the event's repository policy; check permitted registry visibility with the organizer if necessary.

Deploy the same service on a reachable container host. It binds to `0.0.0.0`. Put it behind the host's HTTPS proxy with request-size limits and deadlines. The standard-library HTTP server is intentionally small and has limited hardened deployment features; the team should decide whether to replace it with its own production framework/server setup. Required judge endpoints must not need a login, VPN, dashboard, or manual approval.

From a different network, run health and the live tests against the actual public URL. Keep the deployment awake, provider funded, and image/video accessible during judging. No live URL, registry image, or public repository has been created yet.

## Reliability and limitations

- The API waits at most 25 seconds for processing after reading the body. Provider socket timeout is 18 seconds; solver limit is 3 seconds. Measure actual latency: this is not proof of the guide's 30-second end-to-end requirement. A reverse proxy should enforce connection/body deadlines too.
- Up to four jobs run at once. Excess concurrency returns a controlled 500; no unbounded job queue. A timed-out task retains its slot until finished. Tune for your judge load and provider limits.
- Malformed/structurally invalid requests return 400. Invalid model output, infeasible interpretations, provider failures, and solver/replay errors return generic 500 responses without provider details or keys.
- No automatic fallback or retry model is configured. This preserves honest LLM use but sacrifices availability during provider failures. Any added fallback must itself use a generative model and pass the same guardrails.
- Guardrails prove structural/range validity, not that the LLM understood the note correctly. Ground-truth language accuracy requires live tests.
- Overlapping reserves use the maximum; grid caps use the minimum; blocked charge/discharge windows combine. Identical overlapping solar fractions are applied once. Conflicting fractions on the same hour are rejected: the supplied statement does not specify a composition rule. Ask organizers if such scenarios are expected. Do not silently multiply fractions or choose an arbitrary interpretation.
- No exported energy, battery degradation, efficiencies, forecast uncertainty, authentication layer, or campus telemetry is added because the supplied challenge does not ask for these.
- Request body limit is 1 MiB; model response limit is 256 KiB. Only ordinary content-length JSON requests are supported, not chunked request bodies. Inputs reject extra fields and non-finite/negative numbers.
- Official hidden tests, live LLM/provider behavior, external uptime, Docker reproduction, and the broader rulebook remain unverified.

## Credits

- Challenge specification and public synthetic sample data: BUP CSE Fest 2026 organizers. Samples are unmodified except the filename.
- Architecture, code, and tests: developed with AI coding assistance (ChatGPT/Codex, then Claude Code), as permitted under Participant Guide §04. The team reviewed, tested, and is responsible for the logic actually submitted; see `TEAM_DECISIONS.md` for the team's own account of what it changed and why.
- Python standard library (PSF), NumPy, SciPy, and the HiGHS solver shipped through SciPy; see their distributions for license notices.
- Docker base image: Python official image. Language-model provider and model: **not yet selected; record the actual choice here before submitting.**

## Remaining work before submission

- [ ] Select and configure a real LLM provider/model in `.env` and document it in [Model configuration](#model-configuration) and [Credits](#credits).
- [ ] Run `scripts/test_live.py` against the live-model-backed server and record real pass counts/p95 in `VERIFICATION.md`.
- [ ] Build, run, and verify the Docker image (`docker build` / `docker run` / `/health`); publish a pullable tag or digest.
- [ ] Deploy the service publicly and verify both endpoints are reachable from outside the development network.
- [ ] Fill out `TEAM_DECISIONS.md` with the team's real design decisions and contributions.
- [ ] Record the 3-minute architecture/solution video.
- [ ] Confirm repository timing/visibility (created after question reveal, private during the event, public after the deadline).

## Submission checklist

- [ ] Core design/logic genuinely developed or adapted by the team; AI/dependency credits accurate.
- [ ] Repository timing and visibility follow the official event rulebook.
- [ ] Actual model/provider recorded and live interpretation tested, including paraphrases.
- [ ] Public base URL works externally for both required endpoints.
- [ ] Real pass counts, latency, and failure behavior measured.
- [ ] Tested, pullable Docker image with exact tag/digest and verified run command.
- [ ] README uses actual deployment/repository/image/model values, not placeholders.
- [ ] Secrets excluded from Git, container, logs, screenshots, and video.
- [ ] Accessible MP4/link of no more than three minutes, with truthful demonstration.
