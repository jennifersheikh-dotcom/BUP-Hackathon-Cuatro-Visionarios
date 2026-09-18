# GridWise — Team Design Decisions

## 1. Overall Architecture

We designed GridWise as a two-stage decision system:

1. The LLM interprets natural-language operator notes.
2. A deterministic optimization layer converts the interpreted directives into a feasible 24-hour energy schedule.

The LLM is therefore used for language understanding rather than directly generating the final energy schedule.

The overall flow is:

```text
Operator Notes
      ↓
LLM Interpretation
      ↓
Deterministic Directive Validation
      ↓
Energy Optimization
      ↓
Independent Replay Validation
      ↓
Verified API Response
```

---

## 2. Why We Use an LLM

Operators may provide instructions in natural language, for example:

* "Reduce solar usage between 10 and 12."
* "Do not charge the battery during the evening."
* "Keep grid consumption below 20 kWh during peak hours."

These instructions cannot be used directly by a mathematical optimizer.

We therefore use the LLM to convert natural-language instructions into a small structured set of directives.

The LLM does not decide the final hourly battery/grid schedule.

---

## 3. Why We Use Deterministic Validation

LLM output can contain invalid or unexpected values.

For example, an LLM could produce:

```text
factor = 1.7
```

or:

```text
hour = 27
```

These values must never directly affect the optimizer.

Therefore, every LLM-generated directive is passed through deterministic validation before it is used.

The validator checks:

* directive type
* note index
* whether the directive applies
* hour ranges
* duplicate hours
* adjustment factors
* required fields
* numerical limits

Invalid directives are rejected or replaced with a safe `no_op` interpretation.

---

## 4. Why We Use an Optimization Model

After the operator instructions have been interpreted and validated, the system still needs to determine how the available energy should be distributed across the 24 hours.

We formulate this as a linear optimization problem.

The optimizer determines:

* grid energy
* solar energy usage
* battery charging/discharging
* battery state of charge

while satisfying the physical and operational constraints.

The objective is to minimize the total electricity cost.

---

## 5. Battery Representation

We represent battery flow using a signed variable:

```text
q[h] > 0  → charging
q[h] < 0  → discharging
```

The battery energy is updated using:

```text
E[h+1] = E[h] + charge[h] - discharge[h]
```

We enforce:

* minimum battery reserve
* maximum battery capacity
* maximum charging rate
* maximum discharging rate
* initial battery energy
* end-of-day battery neutrality

The final battery energy must equal the initial battery energy.

---

## 6. Handling Solar

Solar generation is treated as an available upper bound rather than something that must always be consumed.

The optimizer can therefore decide how much solar to use while respecting:

```text
0 ≤ solar_used[h] ≤ solar_available[h]
```

If a `solar_reduction` directive applies to a particular hour, the available solar amount is reduced according to the validated factor.

---

## 7. Handling Grid Limits

Some operator instructions can impose a maximum amount of grid energy for particular hours.

After validation, these limits become deterministic constraints in the optimization problem.

This prevents the LLM from directly manipulating the final schedule.

---

## 8. Why We Replay the Final Schedule

We do not rely only on the optimizer's returned result.

After optimization, the resulting schedule is independently replayed and checked against the original scenario.

The replay validator checks:

* hourly energy balance
* battery state transitions
* battery reserve
* battery capacity
* charge/discharge limits
* solar availability
* grid limits
* charge restrictions
* discharge restrictions
* end-of-day battery neutrality
* total grid consumption
* total cost

Only a schedule that passes these checks is returned as the final result.

---

## 9. Error Handling Philosophy

We separate language errors from physical/optimization errors.

For example:

```text
Natural-language interpretation error
        ↓
Directive validation
        ↓
Safe rejection / no_op
```

while:

```text
Valid directives
        ↓
Optimization infeasibility
        ↓
API error response
```

This prevents an invalid LLM interpretation from silently producing an invalid energy schedule.

---

## 10. Testing Strategy

We use multiple levels of testing:

### Unit / deterministic tests

These test validation, optimization, and replay behavior without requiring an external LLM.

### Public sample cases

The optimizer is tested against the provided public scenarios.

### Live API tests

The complete pipeline is tested with the actual configured LLM and API server.

### Docker tests

The application is also tested inside the Docker container to verify that the packaged application can run independently of the development environment.

---

## ## 11. Team Contributions

The project was developed collaboratively, with team members contributing to different parts of the system.

### Member 1 — [Bushra Jeniffer]

* Worked on the overall system architecture.
* Designed the flow from operator notes to LLM interpretation, validation, optimization, and replay verification.
* Helped integrate the different modules.

### Member 2 — [Saadab Rahman Ridmi]

* Worked on the LLM interpretation layer.
* Designed and tested prompts for converting operator notes into structured directives.
* Worked on handling different forms of natural-language operator instructions.

### Member 3 — [Mohammed Seraz Alam]

* Worked on the optimization model.
* Implemented the battery, solar, grid, and energy-balance constraints.
* Tested the optimizer against the provided sample scenarios.

### Member 4 — [Hrishit Talukder]

* Worked on deterministic validation and replay verification.
* Tested invalid directives and constraint violations.
* Helped with API testing, Docker testing, and submission preparation.

### Collaborative Work

All team members participated in:

* reviewing the problem requirements,
* discussing design decisions,
* testing the complete system,
* debugging integration issues, and
* preparing the documentation and final submission.


## 12. Design Principle

Our main design principle is

Use the LLM for interpretation, and deterministic code for decisions that must obey physical and numerical constraints.

This separation makes the system easier to test, reproduce, and verify.

