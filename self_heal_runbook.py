#!/usr/bin/env python3
"""self-heal-runbook: declarative fault-signature -> diagnostics -> remediation
-> verification runbooks with a strict validator and a zero-side-effect planner.

A runbook is JSON. The validator enforces unique step ids, non-empty phases,
trigger schema, requires-DAG acyclicity, and the closed-loop rule (every
remediation step must be covered by at least one verification step). The
planner topologically orders steps and never executes anything.
"""
from __future__ import annotations

import argparse
import json
import sys

__version__ = "0.1.1"

PHASES = ("diagnostics", "remediation", "verification", "rollback")
PHASE_INDEX = {p: i for i, p in enumerate(PHASES)}
TRIGGER_TYPES = ("log_signature", "metric", "manual", "alert")


class RunbookError(ValueError):
    """Raised when a runbook is invalid."""


def _validate_step(phase, index, step, ids, errors):
    if not isinstance(step, dict):
        errors.append("%s[%d]: step must be an object" % (phase, index))
        return None
    sid = step.get("id")
    if not isinstance(sid, str) or not sid.strip() or sid.strip() != sid:
        errors.append("%s[%d]: step needs a non-blank id without surrounding whitespace"
                      % (phase, index))
        sid = None
    elif sid in ids:
        errors.append("duplicate step id: %s" % sid)
    else:
        ids.add(sid)
    command = step.get("command")
    if not isinstance(command, str) or not command.strip():
        errors.append("%s[%d]: missing non-empty 'command'" % (phase, index))
    requires = step.get("requires", [])
    if not isinstance(requires, list) or any(not isinstance(r, str) for r in requires):
        errors.append("%s[%d]: 'requires' must be a list of ids" % (phase, index))
    timeout = step.get("timeout_s", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        errors.append("%s[%d]: 'timeout_s' must be a positive number" % (phase, index))
    if phase == "remediation":
        attempts = step.get("max_attempts", 1)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            errors.append("%s[%d]: 'max_attempts' must be an integer >= 1" % (phase, index))
    if phase == "verification":
        verifies = step.get("verifies", [])
        if not isinstance(verifies, list) or any(not isinstance(v, str) for v in verifies):
            errors.append("%s[%d]: 'verifies' must be a list of ids" % (phase, index))
    return sid


def _as_list(value):
    """Return value if it is a list of ids, else [] (validator already flagged it)."""
    return value if isinstance(value, list) else []


def validate(rb):
    """Validate a runbook dict; returns a list of error strings (empty = valid)."""
    if not isinstance(rb, dict):
        return ["runbook must be a JSON object"]
    errors = []
    name = rb.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("missing non-empty 'name'")
    if not isinstance(rb.get("runbook_version", "1.0"), str):
        errors.append("'runbook_version' must be a string")
    triggers = rb.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        errors.append("'triggers' must be a non-empty list")
    else:
        for i, trigger in enumerate(triggers):
            if not isinstance(trigger, dict):
                errors.append("trigger %d must be an object" % i)
                continue
            if trigger.get("type") not in TRIGGER_TYPES:
                errors.append("trigger %d: type must be one of %s" % (i, "/".join(TRIGGER_TYPES)))
            if not isinstance(trigger.get("pattern"), str) or not trigger["pattern"].strip():
                errors.append("trigger %d: missing non-empty 'pattern'" % i)
    ids = set()
    all_steps = []
    for phase in PHASES:
        steps = rb.get(phase, [])
        if phase == "rollback" and steps == []:
            continue
        if not isinstance(steps, list) or not steps:
            if phase != "rollback":
                errors.append("'%s' must be a non-empty list" % phase)
            continue
        for i, step in enumerate(steps):
            sid = _validate_step(phase, i, step, ids, errors)
            if sid:
                all_steps.append((phase, i, step, sid))
    for phase, i, step, sid in all_steps:
        for r in _as_list(step.get("requires")):
            if r not in ids:
                errors.append("step %s: requires unknown id %s" % (sid, r))
    covered = set()
    for phase, i, step, sid in all_steps:
        if phase == "verification":
            covered.update(_as_list(step.get("verifies")))
    for phase, i, step, sid in all_steps:
        if phase == "remediation" and sid not in covered:
            errors.append("remediation %s is not covered by any verification step (closed-loop rule)" % sid)
    graph = {}
    for phase, i, step, sid in all_steps:
        graph[sid] = list(_as_list(step.get("requires")))
    cycle = _find_cycle(graph)
    if cycle:
        errors.append("dependency cycle involving: %s" % ", ".join(sorted(cycle)))
    return errors


def _find_cycle(graph):
    remaining = set(graph)
    done = set()
    progress = True
    while remaining and progress:
        progress = False
        for node in sorted(remaining):
            unmet = [r for r in graph[node] if r in graph and r not in done]
            if not unmet:
                done.add(node)
                remaining.discard(node)
                progress = True
                break
    return remaining


def plan(rb):
    """Deterministic topological plan: list of {id, phase, command}.
    Raises RunbookError on invalid input or unresolvable ordering."""
    errors = validate(rb)
    if errors:
        raise RunbookError("invalid runbook: %s" % "; ".join(errors))
    seq = {}
    for phase in PHASES:
        for i, step in enumerate(rb.get(phase, []) or []):
            if isinstance(step, dict) and isinstance(step.get("id"), str):
                seq[step["id"]] = (PHASE_INDEX[phase], i, phase, step)
    order = []
    done = set()
    while len(order) < len(seq):
        candidates = []
        for sid, (pidx, i, phase, step) in seq.items():
            if sid in done:
                continue
            reqs = _as_list(step.get("requires"))
            if all(r in done or r not in seq for r in reqs):
                candidates.append((pidx, i, sid))
        if not candidates:
            raise RunbookError("unresolvable ordering (cycle) among: %s" % sorted(set(seq) - done))
        # emit only the earliest-phase candidates this round so that later
        # phases never overtake unfinished earlier ones
        min_pidx = min(c[0] for c in candidates)
        for _, _, sid in sorted(c for c in candidates if c[0] == min_pidx):
            pidx, i, phase, step = seq[sid]
            order.append({"id": sid, "phase": phase, "command": step["command"]})
            done.add(sid)
    return order


def dry_run(rb):
    """Validate + plan without executing anything. Returns a report dict."""
    errors = validate(rb)
    result = {"valid": not errors, "errors": errors, "plan": []}
    if not errors:
        result["plan"] = plan(rb)
    return result


def load_runbook(data):
    """Load a runbook from a JSON string or dict; raises RunbookError when invalid."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RunbookError("runbook is not valid JSON: %s" % exc) from None
    errors = validate(data)
    if errors:
        raise RunbookError("invalid runbook: %s" % "; ".join(errors))
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(prog="self-heal-runbook", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_v = sub.add_parser("validate", help="validate a runbook file")
    p_v.add_argument("file")
    p_p = sub.add_parser("plan", help="print the dry-run execution plan (executes nothing)")
    p_p.add_argument("file")
    args = parser.parse_args(argv)
    try:
        with open(args.file, "r", encoding="utf-8") as fh:
            rb = load_runbook(fh.read())
    except (OSError, RunbookError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    if args.command == "validate":
        print("OK")
        return 0
    print(json.dumps({"plan": plan(rb)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
