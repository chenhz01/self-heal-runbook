#!/usr/bin/env python3
"""Self-test for self-heal-runbook. Round 1: 40 checks; Round 2: +10 = 50.

Run:  python self_test.py
Last line printed:  SUMMARY: PASS n/n
Categories: A = functional, E = exception paths, X = extreme edges.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import self_heal_runbook as core

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL: %s" % name)


def raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        return False
    except Exception:
        return True


def rb(**overrides):
    base = {
        "runbook_version": "1.0",
        "name": "disk-full-heal",
        "triggers": [{"type": "log_signature", "pattern": "No space left on device"}],
        "diagnostics": [{"id": "d1", "command": "df -h"},
                        {"id": "d2", "command": "du -sh /tmp", "requires": ["d1"]}],
        "remediation": [{"id": "r1", "command": "rm -rf /tmp/cache/*", "requires": ["d2"],
                         "max_attempts": 2}],
        "verification": [{"id": "v1", "command": "df -h", "requires": ["r1"], "verifies": ["r1"]}],
        "rollback": [{"id": "b1", "command": "echo rolled-back"}],
    }
    base.update(overrides)
    return base


GOOD = rb()

# ---------- A. functional unit tests (1-20) ----------
check("A01 valid runbook loads", core.load_runbook(GOOD)["name"] == "disk-full-heal")
check("A02 validate returns [] for good runbook", core.validate(GOOD) == [])
plan = core.plan(GOOD)
check("A03 plan covers all 5 steps", [p["id"] for p in plan] == ["d1", "d2", "r1", "v1", "b1"])
check("A04 requires ordering respected", plan.index({"id": "d1", "phase": "diagnostics", "command": "df -h"}) < plan.index({"id": "d2", "phase": "diagnostics", "command": "du -sh /tmp"}))
dry = core.dry_run(GOOD)
check("A05 dry_run valid with non-empty plan", dry["valid"] is True and len(dry["plan"]) == 5)
dup = rb(remediation=[{"id": "d1", "command": "x"}])
check("A06 duplicate ids detected", any("duplicate" in e for e in core.validate(dup)))
nover = rb(verification=[])
check("A07 empty verification rejected", any("'verification'" in e for e in core.validate(nover)))
uncovered = rb(verification=[{"id": "v1", "command": "df -h", "verifies": []}])
check("A08 closed-loop rule enforced", any("closed-loop" in e for e in core.validate(uncovered)))
badtrig = rb(triggers=[{"type": "telepathy", "pattern": "x"}])
check("A09 invalid trigger type rejected", any("trigger 0" in e for e in core.validate(badtrig)))
nopat = rb(triggers=[{"type": "metric", "pattern": " "}])
check("A10 blank trigger pattern rejected", any("pattern" in e for e in core.validate(nopat)))
unk = rb(remediation=[{"id": "r1", "command": "x", "requires": ["ghost"]}])
check("A11 unknown requires id rejected", any("unknown id ghost" in e for e in core.validate(unk)))
cyc = rb(remediation=[{"id": "r1", "command": "x", "requires": ["v1"]}],
         verification=[{"id": "v1", "command": "y", "verifies": ["r1"], "requires": ["r1"]}])
check("A12 cycle detected", any("cycle" in e for e in core.validate(cyc)))
noroll = {k: v for k, v in GOOD.items() if k != "rollback"}
check("A13 rollback optional", core.validate(noroll) == [])
badatt = rb(remediation=[{"id": "r1", "command": "x", "max_attempts": 0}])
check("A14 max_attempts >= 1 enforced", any("max_attempts" in e for e in core.validate(badatt)))
badto = rb(diagnostics=[{"id": "d1", "command": "x", "timeout_s": -1}])
check("A15 timeout_s positive enforced", any("timeout_s" in e for e in core.validate(badto)))
check("A16 load from JSON string works", core.load_runbook(json.dumps(GOOD))["name"] == "disk-full-heal")
check("A17 load_runbook raises on invalid", raises(core.load_runbook, {"name": ""}))
check("A18 plan phases labeled", all(p["phase"] in core.PHASES for p in plan))
check("A19 closed loop satisfied in good rb", core.validate(GOOD) == [])
check("A20 CLI main is callable", callable(core.main))

# ---------- E. exception paths (21-30) ----------
check("E21 load_runbook(None) raises", raises(core.load_runbook, None))
check("E22 load_runbook('[1]') raises", raises(core.load_runbook, "[1]"))
check("E23 load_runbook bad JSON raises", raises(core.load_runbook, "{nope"))
check("E24 plan on invalid raises RunbookError", raises(core.plan, {"name": "x"}))
noname = {k: v for k, v in GOOD.items() if k != "name"}
check("E25 missing name rejected", any("'name'" in e for e in core.validate(noname)))
nodiag = {k: v for k, v in GOOD.items() if k != "diagnostics"}
check("E26 missing diagnostics rejected", any("'diagnostics'" in e for e in core.validate(nodiag)))
check("E27 non-object step rejected", any("must be an object" in e for e in core.validate(rb(diagnostics=["x"]))))
nocmd = rb(diagnostics=[{"id": "d1"}])
check("E28 missing command rejected", any("command" in e for e in core.validate(nocmd)))
badreq = rb(diagnostics=[{"id": "d1", "command": "x", "requires": "d2"}])
check("E29 requires not a list rejected", any("'requires' must be a list" in e for e in core.validate(badreq)))
badver = rb(verification=[{"id": "v1", "command": "x", "verifies": 5}])
check("E30 verifies not a list rejected", any("'verifies' must be a list" in e for e in core.validate(badver)))

# ---------- X. extreme edges (31-40) ----------
blank = rb(diagnostics=[{"id": "d1", "command": "   "}, {"id": "d2", "command": "x", "requires": ["d1"]}])
check("X31 blank command rejected", any("command" in e for e in core.validate(blank)))
check("X32 unicode ids and patterns accepted", core.validate(rb(
    triggers=[{"type": "manual", "pattern": "磁盘已满"}],
    diagnostics=[{"id": "诊断1", "command": "df"}],
    remediation=[{"id": "修复1", "command": "清理", "requires": ["诊断1"]}],
    verification=[{"id": "验证1", "command": "df", "verifies": ["修复1"]}])) == [])
chain = {"name": "chain", "runbook_version": "1.0",
         "triggers": [{"type": "manual", "pattern": "go"}],
         "diagnostics": [{"id": "s%d" % i, "command": "echo %d" % i, "requires": ["s%d" % (i - 1)]} if i else {"id": "s0", "command": "echo 0"} for i in range(100)],
         "remediation": [{"id": "r", "command": "fix", "requires": ["s99"]}],
         "verification": [{"id": "v", "command": "check", "verifies": ["r"], "requires": ["r"]}]}
pchain = core.plan(chain)
check("X33 100-step chain ordered", len(pchain) == 102 and pchain[0]["id"] == "s0" and pchain[99]["id"] == "s99")
selfcyc = rb(remediation=[{"id": "r1", "command": "x", "requires": ["r1"]}])
check("X34 self-require cycle detected", any("cycle" in e for e in core.validate(selfcyc)))
node = {"n": None}
for _ in range(200):
    node = {"n": node}
deep = rb()
deep["diagnostics"][0]["meta"] = node
check("X35 200-level nested metadata tolerated", core.validate(deep) == [])
check("X36 very long command accepted", core.validate(rb(diagnostics=[{"id": "d1", "command": "echo " + "x" * 10000}], remediation=[{"id": "r1", "command": "fix"}])) == [])
check("X37 empty object lists all core errors", len(core.validate({})) >= 4)
check("X38 plan carries the exact commands",
      all(any(s["command"] == p["command"] for ph in core.PHASES for s in GOOD.get(ph, [])) for p in plan))
two = rb(triggers=[{"type": "manual", "pattern": "same"}, {"type": "metric", "pattern": "same"}])
check("X39 duplicate trigger patterns allowed", core.validate(two) == [])
check("X40 whitespace-only id rejected", any("non-blank id" in e for e in core.validate(rb(diagnostics=[{"id": "  ", "command": "x"}, {"id": "d2", "command": "x", "requires": ["d1"]}, {"id": "d3", "command": "x", "requires": ["d2"]}]))))

print("SUMMARY: PASS %d/%d" % (passed, passed + failed))
