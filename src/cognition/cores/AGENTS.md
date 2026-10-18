# Cores: contributor guide

Applies to `src/cognition/cores/` and any new agent.

## Folder per agent

```
cores/<core>/
  __init__.py     build_agent() and the core spec
  README.md       purpose, authority, escalation, tools and skills tables, how to test
  agent.py        assembly only: model, instruction, tools, skills, schema, callbacks
  instruction.md  identity, boundaries, output contract. No domain procedures
  schemas.py      tool inputs and outputs (cross-boundary contracts stay in domain.py)
  monitor.py      always-on, deterministic, simulated model. No LLM
  reference.py    offline analyser with the same input and output as the agent
  tools/          one tool per file, one operation per tool, names prefixed `<core>_`
  skills/<kebab-name>/SKILL.md (+ references/, assets/, scripts/)
tests/cores/<core>/   unit tests on monitor, reference analyser, tools, skills
tests/eval/<core>/    ADK eval sets (run only with the owner's approval)
```

Shared skills live in `cores/_shared/skills/`. Helpers live in `cognition.agentkit`.

## Rules

- Instruction holds identity and rules, skills hold procedures, tools hold capabilities.
- Skills follow the Agent Skills spec: `name` is kebab-case and equals the folder name,
  `description` is 1 to 1024 characters and says when to use it, body under 500 lines,
  resources one level deep. A skill never grants authority or names a concrete order.
  `tests/test_skills.py` validates every skill on each run.
- Tools are plain typed functions registered with `@tool(core, kind)` from
  `cognition.agentkit.tools`. Docstring must contain "Use when", "Do not" and "Returns",
  and describe every argument. Large reads take `response_format`, `limit` and filters.
  Never return raw waveforms or frames. Fixable input errors return `tool_error(...)`;
  scope and permission violations raise. Read tools write nothing.
- Tool kinds: `read` (writes nothing), `fleet` (T0/T1 missions through FleetGateway, robot core
  only) and `action` (bound, one per core). Tools take a hidden `CoreContext` as first argument;
  `bind_tool` removes it before the model sees the signature.
- Core agents are off unless `COGNITION_CORE_AGENTS=true`. They are tested offline with
  `scripted_model`; never add a test that calls a live model.
- Action tools take no arguments and are bound to one approved order. The agent cannot change
  parameters but may refuse with a reason.
- Cores never write plant state. Only `Gateway.execute` and `FleetGateway` write.
- No hidden retries. Failures end the run as `failed`; the exception type name is recorded,
  never the message. Cancellation records `interrupted` and re-raises.
- Core to core: typed bus requests for evidence only. No direct agent calls, no loops.
- Tests run on reference analysers with no model call.

## Commands

`ruff check .`, `ruff format --check .`, `mypy src/cognition`, `pytest -q`.
