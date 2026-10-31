#!/usr/bin/env python3
"""Generate tracking/issues.json from the revision-5 docs at the baseline commit.

Task, gate and requirement wording is copied from TASKS.md and SPEC.md as
they were at the baseline commit; only hard line wraps are joined (GitHub
renders single newlines in issue bodies as line breaks).
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "bfcbfa81c120b656232740ed69c5172c41b91fd6"
REPO = "NatePu/usg2bsd"
OUT = ROOT / "tracking" / "issues.json"


def git_show(path):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:{path}"],
                          capture_output=True, text=True, check=True).stdout


TASKS = git_show("docs/TASKS.md")
SPEC = git_show("docs/SPEC.md")
ERRATA = git_show("docs/ERRATA.md")


# ---------------------------------------------------------------- parsing

def parse_task_items(text):
    """Return {id: unwrapped text after the bold title} for '- [ ] **T..' items."""
    items, cur, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^- \[ \] \*\*((?:T\d\.\d+)|G\d)\b", line)
        if m:
            if cur:
                items[cur] = " ".join(buf)
            cur, buf = m.group(1), [line[len("- [ ] "):].strip()]
            continue
        if cur and line.startswith("  ") and line.strip():
            buf.append(line.strip())
            continue
        if cur:
            items[cur] = " ".join(buf)
            cur, buf = None, []
    if cur:
        items[cur] = " ".join(buf)
    return items


def split_top(text, semicolons):
    """Split at top-level sentence ends ('. ' + capital/backtick/asterisk/quote)
    and, if asked, at '; ', outside parentheses and code spans."""
    out, buf, depth, code, i = [], [], 0, False, 0
    while i < len(text):
        ch = text[i]
        buf.append(ch)
        if ch == "`":
            code = not code
        elif not code:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and ch in ".;" and text[i + 1:i + 2] == " ":
                nxt = text[i + 2:i + 3]
                tail = "".join(buf[-5:]).lower()
                is_abbrev = tail.endswith(("e.g.", "i.e.", " vs.", "etc."))
                if ((ch == ";" and semicolons) or
                        (ch == "." and nxt and (nxt.isupper() or nxt in "`*\""))) and not is_abbrev:
                    out.append("".join(buf).strip())
                    buf = []
                    i += 1
        i += 1
    rest = "".join(buf).strip()
    if rest:
        out.append(rest)
    return [s[:-1].rstrip() if s.endswith(";") else s for s in out if s]


def strip_title(text):
    """'**T0.1 Pin the fork.** Fork ...' -> 'Fork ...'."""
    m = re.match(r"^\*\*[^*]+\*\*\s*(.*)$", text)
    return m.group(1) if m else text


def split_done(text):
    m = re.search(r"\*Done\s+when:\*\s*", text)
    if not m:
        return text.strip(), None
    return text[:m.start()].strip(), text[m.end():].strip()


task_text = parse_task_items(TASKS)

req_text = {}
for line in SPEC.splitlines():
    m = re.match(r"^\| (R\d+) \| (.*) \|$", line)
    if m:
        req_text[m.group(1)] = m.group(2).strip()
    if line.startswith("| — | Mode P"):
        req_text["MODEP"] = line.split("|")[2].strip()

gate_text = {}
for line in SPEC.splitlines():
    m = re.match(r"^\| (G\d) [a-z0-9 ]+ \| (.*) \|$", line)
    if m:
        gate_text[m.group(1)] = m.group(2).strip()

trace = {}
in_trace = False
for line in TASKS.splitlines():
    if line.startswith("## Requirement"):
        in_trace = True
        continue
    m = re.match(r"^\| (R\d+) \| (.*?) \| (.*?) \|$", line) if in_trace else None
    if m:
        trace[m.group(1)] = (m.group(2), m.group(3))

errata_by_task = {}
for line in ERRATA.splitlines():
    m = re.match(r"^\| (?:\*\*)?((?:E\d+[a-z]?)|(?:D\d+))(?:\*\*)? \|", line)
    if not m:
        continue
    for t in sorted(set(re.findall(r"\bT\d\.\d+\b", line))):
        errata_by_task.setdefault(t, []).append(m.group(1))


def tids(s):
    return re.findall(r"\bT\d\.\d+\b", s)


implements, verifies = {}, {}
for r, (imp, ver) in trace.items():
    for t in tids(imp):
        implements.setdefault(t, []).append(r)
    for t in tids(ver):
        verifies.setdefault(t, []).append(r)


# ---------------------------------------------------------------- content

TITLES = {
    "T0.1": "T0.1 Pin the fork at c595b86dd344 and record file revisions",
    "T0.2": "T0.2 Build and boot loop: cross-build, TFTP boot, bsd.good recovery",
    "T0.3": "T0.3 Bench and artefacts: bench/ configs, traffic and capture scripts",
    "T0.4": "T0.4 Stock baseline measurements (G0)",
    "T0.5": "T0.5 Probe: PIP VLAN fields in WQE word2",
    "T0.6": "T0.6 Probe: buffer data offsets and WQE LEN",
    "T0.7": "T0.7 Probe: RX groups and CPU mapping",
    "T0.8": "T0.8 Probe: FPA pool levels",
    "T0.9": "T0.9 Probe: interrupt yield mechanism (decides DESIGN §5.6 option A or B)",
    "T1.0": "T1.0 Build integration: pseudo-device flow and the if_flow.h hook API",
    "T1.1": "T1.1 sysctl plumbing: net.flow.* (PF_FLOW, sysctl(8))",
    "T1.2": "T1.2 Flow table core (if_flow.c): SMR hash, pool, kstat, ddb, self-test",
    "T1.3": "T1.3 Generation counter and invalidation bump sites",
    "T1.4": "T1.4 Forwarded mark in ip_forward() and ip_output()",
    "T1.5": "T1.5 vlan helpers: vlan_flow_info() and vlan_flow_lookup()",
    "T1.6": "T1.6 Learn: HOOK B request ring and commit task",
    "T1.7": "T1.7 GC sweep and ARP refresh",
    "T1.8": "T1.8 Mode switch protocol (net.flow.mode)",
    "T1.9": "T1.9 amd64 learn harness (FLOW_TESTHOOK)",
    "T2.1": "T2.1 cnmac MD glue: port op, per-CPU counters, kstats",
    "T2.2": "T2.2 HOOK B in cnmac_start",
    "T2.3": "T2.3 HOOK A in shadow mode (mode 3), proves G1",
    "T2.4": "T2.4 RX budget and yield, proves G2",
    "T2.5": "T2.5 Mode 1 hit path: take, rewrite, batch, flush",
    "T2.6": "T2.6 Correctness and VLAN suites (mode 1)",
    "T2.7": "T2.7 Invalidation, static routing, OSPF and ARP suites (mode 1)",
    "T2.8": "T2.8 Safety suite (mode 1)",
    "T2.9": "T2.9 Control plane at full fast-path load (R12)",
    "T2.10": "T2.10 Measure mode 1 against G0 (R13), proves G3",
    "T3.1": "T3.1 Zero-copy ownership experiment (throwaway)",
    "T3.2": "T3.2 PKO mutex and command-buffer reserve",
    "T3.3": "T3.3 Mode 2 hit path",
    "T3.4": "T3.4 Measure mode 2 against mode 1 (R14)",
    "T4.1": "T4.1 Failure injection",
    "T4.2": "T4.2 DIAGNOSTIC sweep and lock/call-chain audit",
    "T4.3": "T4.3 Soaks: 24 h mixed and 72 h reliability",
    "T4.4": "T4.4 Fork README",
    "T4.5": "T4.5 Rebase hygiene",
}

PHASE = {t: int(t[1]) for t in TITLES}
EPIC_OF = {0: "E-P0", 1: "E-P1", 2: "E-P2", 3: "E-P3", 4: "E-P4"}

ENV = {}
for t in TITLES:
    p = PHASE[t]
    if p == 0:
        ENV[t] = ["env:board", "env:build-host"]
    elif p == 1:
        ENV[t] = ["env:build-host"]
    else:
        ENV[t] = ["env:board", "env:build-host"]
ENV["T0.1"] = ["env:build-host"]
ENV["T0.3"] = ["env:board"]
ENV["T0.4"] = ["env:board"]
ENV["T4.4"] = ["env:desk"]
ENV["T4.5"] = ["env:build-host"]

NEEDS_TEXT = {
    "env:board": "USG-3P board and bench",
    "env:build-host": "OpenBSD build host ({{C2}})",
    "env:desk": "nothing beyond this repository",
}

BLOCKED = {
    "T0.2": ["T0.1", "C2"], "T0.3": ["T0.2"], "T0.4": ["T0.3"],
    "T0.5": ["T0.2"], "T0.6": ["T0.2"], "T0.7": ["T0.2"], "T0.8": ["T0.2"], "T0.9": ["T0.2"],
    "G0": ["T0.4"],
    "T1.0": ["T0.1", "C2"], "T1.1": ["T1.0"], "T1.2": ["T1.1"], "T1.3": ["T1.2"],
    "T1.4": ["T1.3"], "T1.5": ["T1.4"], "T1.6": ["T1.5"], "T1.7": ["T1.6"], "T1.8": ["T1.7"],
    "T1.9": ["T1.4"],
    "T2.1": ["G0", "T1.8", "T1.9"], "T2.2": ["T2.1"], "T2.3": ["T2.2", "T0.5", "T0.6", "T0.7"],
    "G1": ["T2.3"], "T2.4": ["G1", "T0.8", "T0.9"], "G2": ["T2.4"], "T2.5": ["G1", "G2"],
    "T2.6": ["T2.5"], "T2.7": ["T2.5"], "T2.8": ["T2.5"], "T2.9": ["T2.5"], "T2.10": ["T2.5"],
    "G3": ["T2.6", "T2.7", "T2.8", "T2.9", "T2.10"],
    "T3.1": ["G3"], "T3.2": ["T3.1"], "T3.3": ["T3.2", "T0.6"], "T3.4": ["T3.3"],
    "T4.1": ["G3"], "T4.2": ["G3"], "T4.3": ["G3"], "T4.4": ["G3"],
}

GATE_TITLES = {
    "G0": "G0 Gate: stock baseline recorded, go/no-go decided",
    "G1": "G1 Gate: learning validated in shadow mode (mode 3)",
    "G2": "G2 Gate: control plane holds with the slow path saturated (mode 3)",
    "G3": "G3 Gate: mode 1 accepted; decides Phase 3",
}

# Extra references beyond what the task text names explicitly.
EXTRA_REFS = {
    "T0.1": [("SPEC", "1"), ("DESIGN", "7")],
    "T0.2": [("DESIGN", "7")],
    "T0.3": [("DESIGN", "7"), ("SPEC", "7.3")],
    "T0.4": [("SPEC", "7.1"), ("SPEC", "7.3")],
    "T0.9": [("DESIGN", "2"), ("DESIGN", "5.6")],
    "T1.0": [("DESIGN", "3"), ("DESIGN", "3.1")],
    "T1.1": [("SPEC", "6.1"), ("DESIGN", "5.7")],
    "T1.2": [("DESIGN", "4"), ("SPEC", "6.2"), ("SPEC", "6.3")],
    "T1.3": [("DESIGN", "5.4")],
    "T1.4": [("DESIGN", "5.1")],
    "T1.5": [("DESIGN", "3.1")],
    "T1.6": [("DESIGN", "5.3"), ("DESIGN", "5.8")],
    "T1.7": [("DESIGN", "5.5"), ("SPEC", "7.2")],
    "T1.8": [("DESIGN", "5.7"), ("DESIGN", "5.8")],
    "T1.9": [("DESIGN", "5.10")],
    "T2.1": [("DESIGN", "5.9"), ("SPEC", "6.2")],
    "T2.2": [("DESIGN", "5.3")],
    "T2.3": [("DESIGN", "5.2"), ("SPEC", "7.1")],
    "T2.4": [("DESIGN", "5.6"), ("DESIGN", "5.7")],
    "T2.5": [("DESIGN", "5.2"), ("DESIGN", "4")],
    "T2.6": [("SPEC", "7.2"), ("SPEC", "4")],
    "T2.7": [("SPEC", "7.2"), ("DESIGN", "5.4")],
    "T2.8": [("SPEC", "7.2")],
    "T2.9": [("SPEC", "7.2")],
    "T2.10": [("SPEC", "7.1"), ("SPEC", "7.3")],
    "T3.1": [("DESIGN", "A")], "T3.2": [("DESIGN", "A")], "T3.3": [("DESIGN", "A")],
    "T3.4": [("SPEC", "7.3"), ("DESIGN", "A")],
    "T4.2": [("DESIGN", "5.8")], "T4.3": [("SPEC", "7.2")], "T4.4": [("SPEC", "4")],
    "T4.5": [("DESIGN", "3")],
}

SECTION_NAMES = {
    ("SPEC", "1"): "purpose and fork point", ("SPEC", "4"): "behaviour contract",
    ("SPEC", "5"): "requirements", ("SPEC", "6.1"): "sysctl net.flow.*",
    ("SPEC", "6.2"): "kstat counters", ("SPEC", "6.3"): "ddb",
    ("SPEC", "7.1"): "gates", ("SPEC", "7.2"): "tests", ("SPEC", "7.3"): "measurement protocol",
    ("DESIGN", "2"): "facts the design depends on", ("DESIGN", "3"): "components",
    ("DESIGN", "3.1"): "internal interfaces", ("DESIGN", "4"): "data structures",
    ("DESIGN", "5.1"): "forwarded mark", ("DESIGN", "5.2"): "hit path",
    ("DESIGN", "5.3"): "learn", ("DESIGN", "5.4"): "invalidation",
    ("DESIGN", "5.5"): "GC and ARP refresh", ("DESIGN", "5.6"): "RX budget and yield",
    ("DESIGN", "5.7"): "mode switch", ("DESIGN", "5.8"): "locking and lifetime",
    ("DESIGN", "5.9"): "counters", ("DESIGN", "5.10"): "amd64 learn harness",
    ("DESIGN", "7"): "development environment", ("DESIGN", "A"): "appendix A, mode 2",
    ("DESIGN", "B"): "appendix B, mode P", ("DESIGN", "8"): "risks",
}


def refs_in(text):
    found = []
    for doc, sec in re.findall(r"\b(DESIGN|SPEC) §(\d+(?:\.\d+)*)", text):
        found.append((doc, sec))
    if re.search(r"\bappendix A\b", text, re.I):
        found.append(("DESIGN", "A"))
    return found


def ref_link(doc, sec):
    label = f"{doc} §{sec}" if sec not in ("A", "B") else f"DESIGN appendix {sec}"
    name = SECTION_NAMES.get((doc, sec))
    tail = f": {name}" if name else ""
    return f"[{label}]({{{{DOC:{doc}:{sec}}}}}){tail}"


STORY = {
    "R1": ("Must", "Forward routed IPv4 on hits without softnet, ip_input, ip_forward or a route lookup",
           "the router owner",
           "routed IPv4 unicast between the cnmac ports and VLANs to be forwarded on a hit without softnet, `ip_input`, `ip_forward` or a route lookup",
           "one forwarded flow no longer saturates a core and forwarding approaches line rate"),
    "R2": ("Must", "Offloaded packets are routed exactly as the slow path would route them",
           "a host behind the router",
           "an offloaded packet to differ from slow-path output only in TTL, IPv4 header checksum and the L2 header, with the same MACs and 802.1Q TCI (including PCP) the slow path would produce",
           "the fast path is invisible to me"),
    "R3": ("Must", "Everything outside the offload contract takes the slow path",
           "the router owner",
           "everything listed in SPEC §4 item 2, plus misses, stale flows and frames failing any check, to take the slow path",
           "only the simple, verified routed case is accelerated"),
    "R4": ("Must", "Never learn IPsec, tunnel or other non-plain egress",
           "the router owner",
           "a pair whose egress frame came from IPsec, a tunnel, or anything other than plain forwarding out of a cnmac (or a vlan on a cnmac) never to be learned",
           "encapsulated or policy-routed traffic is never forwarded by the fast path"),
    "R5": ("Must", "Hit path is non-sleeping, lock-free on lookup and allocation-free",
           "the kernel maintainer",
           "HOOK A and batch transmit to use no sleeping locks, look flows up under SMR without a flow-table writer lock, and add no per-hit allocation beyond the existing receive/refill and transmit machinery",
           "the hit path is safe in interrupt context and cheap per packet"),
    "R6": ("Must", "Buffers and WQEs returned exactly once; FPA levels in kstat",
           "the kernel maintainer",
           "every packet buffer and WQE returned exactly once and the FPA pool levels observable in kstat",
           "a leak shows up before it exhausts the 768-buffer packet pool"),
    "R7": ("Must", "net.flow.mode=0 is a complete off switch",
           "the router owner",
           "setting `net.flow.mode=0` to return only once the flow table and learn ring are empty, no old producer or worker can repopulate them, and RX uses the stock loop and interrupt settings",
           "I have a trustworthy off switch for recovery and for A/B comparison"),
    "R8": ("Must", "Invalidate at admission on every relevant change; refresh ARP fairly",
           "the router owner",
           "every relevant route, ARP, interface, VLAN, bridge/trunk, monitor, bpf, sysctl, pf or IPsec change to invalidate cached flows at admission, and the next hops of active flows to be refreshed in ARP",
           "offloaded traffic never follows a stale forwarding decision beyond the documented queue tail"),
    "R9": ("Must", "Rejected packets reach the slow path unmodified",
           "the router owner",
           "a packet the fast path rejects to reach the slow path unmodified",
           "falling back is always transparent"),
    "R10": ("Must", "Respect link and running state of ports, VLANs and parents",
            "the router owner",
            "hits to require both physical ports running with link, and commits to require both logical interfaces and their parents up and running with usable links",
            "no offloaded traffic crosses a down link or a disabled VLAN"),
    "R11": ("Must", "Offload all supported VLAN topologies with slow-path PCP",
            "a VLAN user",
            "untagged↔tagged, tagged↔tagged (different VIDs) and inter-VLAN routing on one trunk to be offloaded, with egress PCP exactly as the slow path sets it",
            "my VLAN deployment gets the full speedup without changing priority behaviour"),
    "R12": ("Must", "Control plane stays healthy at maximum load",
            "the router owner",
            "OSPF adjacencies to stay FULL, ARP to resolve and the shell to stay usable at maximum offered load on both cores",
            "acceleration never costs me the control plane"),
    "R13": ("Should", "Mode 1 reaches the performance targets (provisional)",
            "the router owner",
            "mode 1 to reach ≥ 900 Mbit/s at 1500-byte IPv4 packets and ≥ 100 kpps at 64-byte frames per direction on two ports (aggregate on one inter-VLAN trunk), measured per SPEC §7.3",
            "the USG-3P routes at close to line rate; the targets are restated after G0"),
    "R14": ("Should", "Keep mode 2 only if it measurably beats mode 1",
            "the kernel maintainer",
            "zero-copy mode 2 to be kept only if it beats mode 1 by a measured margin that justifies its risk",
            "we do not carry the riskiest buffer-ownership invariants for no gain"),
    "R15": ("Could, deferred", "PPPoE encapsulation (deferred)",
            "a PPPoE user",
            "PPPoE-encapsulated traffic to be offloaded",
            "a PPPoE uplink benefits too; not part of this release"),
    "R16": ("Must", "Learn only when pf cannot filter the path",
            "the router owner",
            "mode R to learn only when pf is not running, or both the ingress and egress logical interfaces are `set skip`",
            "offload never bypasses active filtering"),
    "MODEP": ("Could, deferred", "Mode P: learn from pf states (deferred)",
              "a future deployment that wants filtering on offloaded paths",
              "flows learned from pf states (mode P) so that filtered traffic can be offloaded",
              "firewalled paths can be accelerated too; specified in DESIGN appendix B, not scheduled"),
}

STORY_ORDER = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12",
               "R13", "R14", "R15", "R16", "MODEP"]

STORY_CONTRACT = {
    "R2": "SPEC §4 item 3", "R3": "SPEC §4 item 2", "R8": "SPEC §4 items 5 and 6",
    "R11": "SPEC §4 item 4 (queue priority)", "R16": "SPEC §4 item 9", "R4": "SPEC §4 item 9",
}


def issue(key, title, labels, body, parent=None, blocked_by=None, state="open",
          state_reason=None, pin=False):
    return {"key": key, "title": title, "labels": labels, "body": body.strip() + "\n",
            "parent": parent, "blocked_by": blocked_by or [], "state": state,
            "state_reason": state_reason, "pin": pin, "comments": [], "number": None}


def bullets(items):
    return "\n".join(f"- {x}" for x in items)


def checklist(items):
    return "\n".join(f"- [ ] {x}" for x in items)


PROTOCOL = ("<sub>Work protocol (AGENTS.md): comment before you start, at every checkpoint and with "
            "evidence when done; close only when every Done-when item is verified on the stated "
            "environment. Findings against the docs get their own `finding` issue.</sub>")

ORIGIN = ("Migrated from [TASKS.md]({{BASELINE:docs/TASKS.md}}) revision 5 (2026-10-31). The task and "
          "Done-when wording below is unchanged; only line wraps were joined.")


# ---------------------------------------------------------------- tasks

def task_body(t):
    raw = task_text.get(t, "")
    if t in ("T3.3", "T3.4"):
        scope_text = {
            "T3.3": "Mode 2 hit path (headroom per T0.6; IPD skip change only if needed).",
            "T3.4": "Measure mode 2 against mode 1 (R14).",
        }[t]
        done_text = None
    else:
        scope_text, done_text = split_done(strip_title(raw))
        scope_text = scope_text.removeprefix("(throwaway): ")
    scope = split_top(scope_text, semicolons=False)
    rows = [("Phase", f"Phase {PHASE[t]} ({{{{{EPIC_OF[PHASE[t]]}}}}})"),
            ("Needs", " · ".join(NEEDS_TEXT[e] for e in ENV[t]))]
    if BLOCKED.get(t):
        rows.append(("Blocked by", " · ".join(f"{{{{{b}}}}}" for b in BLOCKED[t])))
    if implements.get(t):
        rows.append(("Implements", " · ".join(f"{r} {{{{{r}}}}}" for r in implements[t])))
    if verifies.get(t):
        rows.append(("Verifies", " · ".join(f"{r} {{{{{r}}}}}" for r in verifies[t])))
    if errata_by_task.get(t):
        rows.append(("Errata naming it", ", ".join(errata_by_task[t]) +
                     " ([ERRATA.md]({{REPO_URL}}/blob/main/docs/ERRATA.md))"))
    table = "| | |\n|---|---|\n" + "\n".join(f"| {a} | {b} |" for a, b in rows)
    parts = [ORIGIN if t not in ("T3.3", "T3.4") else ORIGIN.replace(
        "The task and Done-when wording below is unchanged; only line wraps were joined.",
        "TASKS.md listed T3.3 and T3.4 in one bullet; they are split here."), "", table, "",
        "### Task", "", bullets(scope), "", "### Done when", ""]
    if done_text:
        parts.append(checklist(split_top(done_text, semicolons=True)))
    elif t.startswith("T3.") or t in ("T4.1", "T4.2", "T4.4", "T4.5"):
        parts.append("- [ ] TASKS.md gives no separate Done-when for this item: every point listed "
                     "under Task is done and recorded. Agree a sharper exit criterion in a comment "
                     "before starting.")
    mentioned = [x for x in dict.fromkeys(re.findall(r"\b(?:T\d\.\d+|G\d)\b", scope_text + " " + (done_text or "")))
                 if x != t]
    reqs = list(dict.fromkeys(re.findall(r"\bR\d+\b", scope_text + " " + (done_text or ""))))
    refs = list(dict.fromkeys(refs_in(scope_text + " " + (done_text or "")) + EXTRA_REFS.get(t, [])))
    if mentioned or reqs:
        parts += ["", "### Related issues", "",
                  bullets([f"{x} {{{{{x}}}}}" for x in mentioned] + [f"{r} {{{{{r}}}}}" for r in reqs])]
    if refs:
        parts += ["", "### References", "", bullets([ref_link(d, s) for d, s in refs])]
    parts += ["", PROTOCOL]
    return "\n".join(parts)


# ---------------------------------------------------------------- gates

GATE_INFO = {
    "G0": {
        "phase": 0,
        "decides": "Go/no-go for the fork, and whether R13 must be restated because the stock slow path is already near wire speed (TASKS: \"G0 — baseline recorded, R13 restated if needed, go/no-go decided.\").",
        "evidence": ["Baseline table in NOTES.md, with the SPEC §7.3 durations, repeats, loss and per-direction/aggregate results ({{T0.4}}).",
                     "Static-route and OSPF-route runs, untagged and inter-VLAN, LRO on and off, per-core CPU.",
                     "The decision, as a comment here, and SPEC R13 updated if restated."],
        "feeds": ["T0.1", "T0.2", "T0.3", "T0.4"],
        "next": "Phase 2 entry also needs successful T0.2 and Phase 1 with its amd64 checks; T2.3 needs T0.5–T0.7 and T2.4 needs T0.8/T0.9.",
    },
    "G1": {
        "phase": 2,
        "decides": "That learning, admission and invalidation are correct before any packet is taken (mode 3 counts only).",
        "evidence": ["Counters under iperf/pktgen load showing `hit` equal to the packets of learned pairs within 1 % ({{T2.3}}).",
                     "Each `ref_*` refusal test and each invalidation test (stale rejection or miss after GC, then relearn).",
                     "QinQ, VID-0, IPv6, ARP, multicast, TTL-1 and oversize frames counted as `sl_*`, never `hit`."],
        "feeds": ["T2.1", "T2.2", "T2.3"],
        "next": "T2.4 (budget and yield) and, with G2, T2.5 (mode 1).",
    },
    "G2": {
        "phase": 2,
        "decides": "That the bounded RX loop and the hardware-timed yield keep the control plane alive before mode 1 is enabled.",
        "evidence": ["OSPF FULL for 1 h in mode 3 with the slow path saturated at 64 B on both ports; no FPA pool drift ({{T2.4}}).",
                     "Mode 0 with a yield re-arm pending restores stock POW thresholds and `POW_WQ_INT_PC`; no late callback; no yields after the setter returns.",
                     "Recorded budget/yield settings and the T0.9 mechanism they rely on."],
        "feeds": ["T0.8", "T0.9", "T2.4"],
        "next": "T2.5 (mode 1 hit path).",
    },
    "G3": {
        "phase": 2,
        "decides": "Mode 1 acceptance, and whether Phase 3 (zero-copy mode 2) is worth starting. R13 is a milestone, not a stopping point: record the remaining bottlenecks and the next useful optimization, or evidence that the workload is at its link limit.",
        "evidence": ["All SPEC §7.2 functional, VLAN, invalidation, race, ordering, ARP, safety and 1-hour control-plane tests pass in mode 1 ({{T2.6}}–{{T2.9}}).",
                     "R13 measured per SPEC §7.3 and compared with G0; results in NOTES.md ({{T2.10}}).",
                     "The Phase 3 decision and further mode-1 optimization work, as a comment here. Multi-day soaks are verified later in {{T4.3}} (ERRATA D15)."],
        "feeds": ["T2.5", "T2.6", "T2.7", "T2.8", "T2.9", "T2.10"],
        "next": "Phase 3 (optional) and Phase 4.",
    },
}


def gate_body(g):
    info = GATE_INFO[g]
    parts = [f"Acceptance gate from [SPEC §7.1]({{{{DOC:SPEC:7.1}}}}). Gates are hard stops: work that depends on this gate does not start until it is closed with evidence.", "",
             "### Pass condition (SPEC §7.1, verbatim)", "", f"> {gate_text[g]}", "",
             "### Decides", "", info["decides"], "",
             "### Evidence to attach before closing", "", checklist(info["evidence"]), "",
             "### Fed by", "", bullets([f"{TITLES.get(x, x)} {{{{{x}}}}}" for x in info["feeds"]]), "",
             "### Unblocks", "", info["next"], "", PROTOCOL]
    return "\n".join(parts)


# ---------------------------------------------------------------- stories

def story_body(r):
    prio, _, who, want, why = STORY[r]
    imp, ver = trace.get(r, ("", ""))
    parts = [f"**As** {who}, **I want** {want}, **so that** {why}.", ""]
    if r == "MODEP":
        parts += ["### Requirement (SPEC §5, Could / deferred, verbatim)", "", f"> Mode P — {req_text['MODEP']}", ""]
    else:
        parts += [f"### Requirement (SPEC §5, {prio}, verbatim)", "", f"> **{r}** — {req_text[r]}", ""]
    if r in ("R15", "MODEP"):
        extra = ("Not part of this release (SPEC §5 \"Could / deferred\"). Closed as not planned; "
                 "reopen if it is scheduled.")
        if r == "MODEP":
            extra += (" The corrected design is [DESIGN appendix B]({{DOC:DESIGN:B}}). Open question "
                      "before starting: whether a forwarded connection under `pass` creates one floating "
                      "pf state or two (ERRATA E7, SPEC §9).")
        parts += ["### Status", "", extra, ""]
    else:
        ver_ids = tids(ver)
        imp_ids = tids(imp)
        acc = [f"Verified by {TITLES[t]} {{{{{t}}}}}" for t in ver_ids]
        parts += ["### Acceptance", "", checklist(acc), "",
                  "Close this story when every verifying issue is closed with evidence that the requirement holds on the stated environment.", "",
                  "### Implemented by", "", bullets([f"{TITLES[t]} {{{{{t}}}}}" for t in imp_ids]), ""]
        notes = re.findall(r"\(([^)]*)\)", imp + " " + ver)
        if notes:
            parts += [f"Traceability notes from TASKS.md: {'; '.join(notes)}.", ""]
    if r in STORY_CONTRACT:
        parts += [f"Behaviour contract: {STORY_CONTRACT[r]} ([SPEC §4]({{{{DOC:SPEC:4}}}})).", ""]
    parts += [f"Source: [SPEC §5]({{{{DOC:SPEC:5}}}}) and the traceability table of [TASKS.md]({{{{BASELINE:docs/TASKS.md}}}})."]
    return "\n".join(parts)


# ---------------------------------------------------------------- epics

def child_list(keys):
    return bullets([f"{(TITLES.get(k) or GATE_TITLES.get(k) or k)} {{{{{k}}}}}" for k in keys])


P0 = [f"T0.{i}" for i in range(1, 10)] + ["G0"]
P1 = [f"T1.{i}" for i in range(0, 10)]
P2 = ["T2.1", "T2.2", "T2.3", "G1", "T2.4", "G2", "T2.5", "T2.6", "T2.7", "T2.8", "T2.9", "T2.10", "G3"]
P3 = ["T3.1", "T3.2", "T3.3", "T3.4"]
P4 = [f"T4.{i}" for i in range(1, 6)]

EPICS = {
    "E-P0": ("Epic: Phase 0 — Board, bench and probes (G0)", ["epic", "phase-0"], P0,
             "Pin and build the fork point, boot it on the USG-3P, wire the bench, measure the stock baseline (G0), and run the hardware probes T0.5–T0.9 that Phase 2 depends on. Phase 0 includes both host builds and board work, and runs in parallel with Phase 1.",
             "T0.1 pin ─ T0.2 build/boot ─ T0.3 bench ─ T0.4 baseline ─► [G0]\nT0.5–T0.9 probes (any order after T0.2)",
             "Needs the OpenBSD build host ({{C2}}) and the board. T0.1's revision table and T0.3's bench files can be written at the desk."),
    "E-P1": ("Epic: Phase 1 — Control plane on amd64 (no board)", ["epic", "phase-1"], P1,
             "Build the MI control plane (flow table, learn, invalidation, GC/ARP, mode switch, sysctl, kstat) so it compiles and self-tests on amd64. Phase 1 needs no USG hardware, but requires a matching OpenBSD amd64 VM/build host.",
             "T1.0 build ─ T1.1 sysctl ─ T1.2 core ─ T1.3 gen ─ T1.4 mark ─ T1.5 vlan\n─ T1.6 learn ─ T1.7 GC/ARP ─ T1.8 mode switch\nT1.9 amd64 harness develops alongside T1.5–T1.8",
             "Code can be written anywhere against the pinned tree; every Done-when needs the build host ({{C2}}). T1.9 can be built alongside T1.5/T1.6 so it validates Phase 1 as work proceeds."),
    "E-P2": ("Epic: Phase 2 — Board: shadow mode, control-plane protection, mode 1 (G1–G3)", ["epic", "phase-2"], P2,
             "Entry requires G0, successful T0.2, and Phase 1 implementation plus its amd64 checks. T2.3 additionally requires T0.5–T0.7; T2.4 requires T0.8/T0.9; T2.5 requires G1 and G2. G3 requires every T2.6–T2.10 check, not only throughput.",
             "T2.1 MD glue ─ T2.2 HOOK B ─ T2.3 shadow ─► [G1] ─ T2.4 budget/yield ─► [G2]\n─ T2.5 mode 1 ─ T2.6..T2.10 tests + measure ─► [G3]",
             "Strictly blocked on G0 and T0.9 (AGENTS.md)."),
    "E-P3": ("Epic: Phase 3 — Zero-copy mode 2 (optional)", ["epic", "phase-3", "optional"], P3,
             "Only if G3 shows a gap worth closing. DESIGN appendix A.",
             "mode 2 zero-copy, only if G3 says so",
             "Starts only on a G3 decision recorded in {{G3}}."),
    "E-P4": ("Epic: Phase 4 — Hardening and acceptance", ["epic", "phase-4"], P4,
             "Failure injection, the DIAGNOSTIC and lock audit, the 24 h/72 h soaks that are final acceptance (ERRATA D15), the fork README and rebase hygiene.",
             "hardening, soaks, README",
             "After G3 (and Phase 3 if it runs)."),
}


def epic_body(key):
    title, labels, children, intro, flow, notes = EPICS[key]
    parts = [intro, "", "```", flow, "```", "", "### Sub-issues", "", child_list(children), "",
             notes, "", "Close this epic when every sub-issue is closed.", "",
             "Plan origin: [TASKS.md]({{BASELINE:docs/TASKS.md}}) revision 5."]
    return "\n".join(parts)


# ---------------------------------------------------------------- chores

C1_BODY = """
On 2026-10-31 the owner asked for the work plan to move to GitHub: epics, user stories and task issues, with **GitHub Issues as the source of truth for all work**, every action checkpointed into its issue, AGENTS.md and CLAUDE.md updated to say so, and Markdown files that are no longer relevant removed.

### Done when

- [ ] Private repository {{REPO_URL}} exists, with the baseline commit `bfcbfa8` (revision-5 docs as found) and the migration commits pushed.
- [ ] Every TASKS.md task (T0.1–T4.5) and gate (G0–G3) is an issue with its wording, phase epic, blockers, requirement links and references.
- [ ] Every SPEC requirement (R1–R16, plus mode P) is a user story under {{E-REQ}}.
- [ ] Open items from JOURNAL.md are issues: build host {{C2}}, fork hosting {{C3}}, review workflow {{C4}}.
- [ ] AGENTS.md and CLAUDE.md state that GitHub Issues are the source of truth and define the checkpoint protocol.
- [ ] TASKS.md and JOURNAL.md are removed; every link to them points to an issue or to the baseline permalink.
- [ ] The roadmap {{ROADMAP}} is pinned.
- [ ] After publication, `tracking/`, `tools/track.py` and the staging paragraph in AGENTS.md are deleted (the issues are the record).

The checkpoint comments below record each step.
"""

C2_BODY = """
Phase 1 and Phase 0 builds need an **OpenBSD -current build host at the pinned source version** ([DESIGN §7]({{DOC:DESIGN:7}})): a full checkout at `/usr/src`, matching installed headers and tools, permission to build there, and the `Makefile.cross` octeon toolchain. The amd64 VM also runs the T1.9 learn harness. Nothing like this exists yet; the development Mac (macOS, arm64) cannot run the build.

This blocks the Done-when of T0.1 (unmodified build), T0.2, T0.5–T0.9 (probe kernels) and every Phase 1 task. Code can be written before it exists.

### Options

1. **Separate amd64 machine or cloud VM** running an OpenBSD -current snapshot, then `make build` and a kernel from the pinned `/usr/src`, so host headers and tools match the fork point exactly. Matches DESIGN §7 as written. *Recommended.*
2. **QEMU on the Mac, amd64 guest under TCG emulation.** Matches DESIGN §7, but emulation makes every kernel build slow (hours), which hurts the Phase 1 edit-build-test loop.
3. **QEMU or UTM on the Mac, arm64 guest with hardware virtualization.** Fast, and the MI flow code is the same on arm64, but it changes DESIGN §7 and T1.9 (amd64), and cross-building octeon from an arm64 host is untested. Needs an ERRATA entry before use.

### Done when

- [ ] The host is reachable by agents (record the ssh alias or access method in AGENTS.md) with `/usr/src` at `c595b86dd344` plus the fork patches ({{C3}}).
- [ ] `config GENERIC.MP` and the DESIGN §7 recipe run, with tool versions recorded in NOTES.md (feeds {{T0.2}}).
- [ ] An amd64 GENERIC.MP kernel builds and boots in the VM (feeds {{T1.0}}).

Owner decision needed: which option, and who provisions it.
"""

C3_BODY = """
T0.1 says "Fork -current at `c595b86dd344`". Where the forked tree lives is not specified. Options:

1. **Patch series in this repository** (`patches/`, made with `git format-patch` against `c595b86dd344`), applied to a checkout of `openbsd/src` by `tools/fork-src.sh`. Small, private, and rebasing means re-applying the series to a newer upstream. **In use as the interim choice** so work can start; see the ruling on {{T0.1}}.
2. **Private mirror repository with full history.** Private and rebase-friendly, but upstream is about 1.7 GB and GitHub limits a single push to 2 GB, so the history has to be pushed in pieces.
3. **Public GitHub fork of `openbsd/src`.** Fastest and rebase-friendly, but GitHub forks of public repositories are public; SPEC §2 calls this a private, non-production fork.

Recommendation: keep option 1 until the build host exists ({{C2}}), then decide whether the build host should pull a branch instead.

### Done when

- [ ] Owner picks an option (comment here).
- [ ] AGENTS.md "Where code lives" matches the choice, and `tools/fork-src.sh` (or its replacement) reproduces the tree.
"""

C4_BODY = """
The saved review workflow `.claude/workflows/usg3p-fastpath-doc-review.js` is stale. Findings from the journal entry of 2026-10-31 08:52 EDT ([JOURNAL.md]({{BASELINE:docs/JOURNAL.md}})):

1. **Blocking: no ground truth.** `SCR`, `SRC`, `CVMX` and `PR` (lines 13–16) point at an earlier session's `/private/tmp` scratch directory, which no longer exists.
2. **It reviews revision 1, not revision 5.** Its CONTEXT describes the permit-any `pass tag OFFLOAD` ruleset, decisions N1..N13, tasks T0A..T3 and requirements up to R21; lens prompts cite DESIGN §9–§10 and SPEC §11, which do not exist.
3. **It re-litigates settled decisions** (judge panel on route cache versus pf-state learning, ERRATA D1; mode 1 versus zero-copy, D2) and keeps a pf-state lens.
4. **The decision record is not an input** (ERRATA, STOCK_TEST_PLAN, and now the GitHub issues).
5. **Results are not kept**: the script only returns JSON.
6. **Cost**: 9 lenses, 3 judges and a dedup agent, then one verifier per medium-or-worse finding; a full run would start well over 100 agents.
7. **Retired input**: it reads `docs/TASKS.md` (line 26 and the lens prompts), retired on 2026-10-31. Read the task issues instead, for example `gh issue list --label task --json number,title,body`.

### Done when

- [ ] Source constants point at a persistent checkout of `c595b86dd344` (plus cvmx headers and the OpenWrt diffs), or the script fetches them.
- [ ] CONTEXT and lens prompts describe revision 5: mode R, mode 1, R1–R16, T0.1–T4.5, D1–D15, DESIGN §1–§8 and appendices.
- [ ] ERRATA and the open `finding` issues are inputs, with "do not re-raise a resolved erratum without new evidence".
- [ ] Judge panel and pf-state lens dropped; verification capped (for example high/critical only).
- [ ] Results are posted as a comment on a review issue instead of only returned.
"""

# ---------------------------------------------------------------- roadmap

def roadmap_body():
    rows = []
    for t in TITLES:
        needs = ", ".join(e.split(":")[1] for e in ENV[t])
        rows.append(f"| {{{{{t}}}}} | {TITLES[t][len(t) + 1:]} | {needs} |")
    task_table = "| Issue | Task | Needs |\n|---|---|---|\n" + "\n".join(rows)
    gates = "\n".join(f"| {{{{{g}}}}} | {gate_text[g]} |" for g in ("G0", "G1", "G2", "G3"))
    trace_rows = []
    for r in [f"R{i}" for i in range(1, 17)]:
        imp, ver = trace[r]
        def link(s):
            return re.sub(r"\b(T\d\.\d+)\b", lambda m: f"{m.group(1)} {{{{{m.group(1)}}}}}", s)
        trace_rows.append(f"| {r} {{{{{r}}}}} | {link(imp)} | {link(ver)} |")
    return f"""
**Start here.** This is the map of all work on the CPU-assisted IPv4 fast path for the OpenBSD/octeon `cnmac(4)` driver on the Ubiquiti USG-3P. GitHub Issues are the source of truth for all work ([AGENTS.md]({{{{REPO_URL}}}}/blob/main/AGENTS.md)); the specification, design and decision record live in [`docs/`]({{{{REPO_URL}}}}/tree/main/docs).

Optimize routing and VLAN throughput and packet rate first. R13 is a milestone, not a stopping point: G3 must record the remaining bottlenecks and the next useful optimization, or evidence that the tested workload is at its link limit. Mode P is not a prerequisite. Phase 0 board work and Phase 1 run in parallel; Phase 2 starts only when its entry conditions are met.

### How the issues are organized

| Kind | Label | What it holds |
|---|---|---|
| Epic | `epic` | One per phase; its sub-issues are that phase's tasks and gates. |
| Task | `task` | One former TASKS.md item (T*), with its verbatim Done-when. |
| Gate | `gate` | SPEC §7.1 hard stops G0–G3 and the decision each records. |
| User story | `user-story` | SPEC requirements R1–R16 (and mode P) under {{{{E-REQ}}}}. |
| Chore | `chore` | Infrastructure and tooling under {{{{E-INFRA}}}}. |
| Finding | `finding` | Doc or code discrepancies; resolved into ERRATA. |

`env:*` labels say what a task's Done-when needs: `env:board` (USG-3P and bench), `env:build-host` (OpenBSD host, {{{{C2}}}}), `env:desk` (this repository only). `needs-owner` marks decisions only the owner can make.

### Phases

```
Phase 0 (host/box) T0.1 pin ─ T0.2 build/boot ─ T0.3 bench ─ T0.4 baseline ─► [G0]
                 T0.5–T0.9 probes (any order after T0.2)
Phase 1 (amd64)  T1.0 build ─ T1.1 sysctl ─ T1.2 core ─ T1.3 gen ─ T1.4 mark ─ T1.5 vlan
                 ─ T1.6 learn ─ T1.7 GC/ARP ─ T1.8 mode switch
                 T1.9 amd64 harness develops alongside T1.5–T1.8
Phase 2 (box)    T2.1 MD glue ─ T2.2 HOOK B ─ T2.3 shadow ─► [G1] ─ T2.4 budget/yield ─► [G2]
                 ─ T2.5 mode 1 ─ T2.6..T2.10 tests + measure ─► [G3]
Phase 3 (opt.)   mode 2 zero-copy, only if G3 says so
Phase 4          hardening, soaks, README
```

| Phase | Epic |
|---|---|
| 0 Board, bench, probes | {{{{E-P0}}}} |
| 1 Control plane on amd64 | {{{{E-P1}}}} |
| 2 Shadow, control plane, mode 1 | {{{{E-P2}}}} |
| 3 Zero-copy mode 2 (optional) | {{{{E-P3}}}} |
| 4 Hardening and acceptance | {{{{E-P4}}}} |
| Requirements as user stories | {{{{E-REQ}}}} |
| Infrastructure and tooling | {{{{E-INFRA}}}} |

### Gates

| Gate | Pass condition (SPEC §7.1) |
|---|---|
{gates}

### Tasks

{task_table}

### Requirement traceability

| Requirement | Implement | Verify |
|---|---|---|
{chr(10).join(trace_rows)}

R15 (PPPoE) {{{{R15}}}} and mode P {{{{MODEP}}}} are deferred.

### Open blockers

- Build host: {{{{C2}}}} (owner decision).
- Fork hosting: {{{{C3}}}} (interim patch series in use).
- Board and bench access for every `env:board` task.

### Documents

[SPEC]({{{{REPO_URL}}}}/blob/main/docs/SPEC.md) (requirements, gates) · [ERRATA]({{{{REPO_URL}}}}/blob/main/docs/ERRATA.md) (binding decisions D*, errata E*) · [DESIGN]({{{{REPO_URL}}}}/blob/main/docs/DESIGN.md) (architecture) · [NOTES]({{{{REPO_URL}}}}/blob/main/docs/NOTES.md) (source facts and results) · [STOCK_TEST_PLAN]({{{{REPO_URL}}}}/blob/main/docs/STOCK_TEST_PLAN.md) (G0 procedure). Retired with this migration: [TASKS.md]({{{{BASELINE:docs/TASKS.md}}}}) and [JOURNAL.md]({{{{BASELINE:docs/JOURNAL.md}}}}) (permalinks to the baseline commit).
"""


def req_epic_body():
    return ("Every SPEC §5 requirement as a user story, with the tasks that implement and verify it "
            "(from the TASKS.md traceability table). A story closes when its verifying issues are closed "
            "with evidence. R15 and mode P are deferred and closed as not planned.\n\n### Sub-issues\n\n" +
            bullets([f"{k if k != 'MODEP' else 'Mode P'} {STORY[k][1]} {{{{{k}}}}}" for k in STORY_ORDER]) +
            "\n\nSource: [SPEC §5]({{DOC:SPEC:5}}).")


INFRA_BODY = """
Work that keeps the project running rather than implementing the fast path: issue tracking, the build host, where the forked source lives, and review tooling.

### Sub-issues

- Move work tracking to GitHub Issues {{C1}}
- Provision the OpenBSD build host {{C2}}
- Decide where the OpenBSD src fork lives {{C3}}
- Update the saved doc-review workflow to revision 5 {{C4}}
"""


# ---------------------------------------------------------------- assemble

LABELS = [
    ("roadmap", "000000", "Top-level map of all work; start here"),
    ("epic", "5319e7", "Groups a phase's tasks and gates as sub-issues"),
    ("task", "0e8a16", "Work item with a verifiable Done-when (former TASKS.md T*)"),
    ("gate", "b60205", "Acceptance gate (SPEC 7.1 G*); a hard stop"),
    ("user-story", "1d76db", "Requirement (SPEC 5 R*) written as a user story"),
    ("chore", "c5def5", "Infrastructure, tracking, tooling or docs work"),
    ("finding", "fbca04", "Doc or code discrepancy with evidence; resolves into ERRATA"),
    ("needs-owner", "d93f0b", "Needs a decision or action from the owner"),
    ("blocked", "e11d21", "Cannot proceed; the latest comment says on what"),
    ("in-progress", "0052cc", "An agent is working on this now"),
    ("phase-0", "fef2c0", "Phase 0: board, bench, probes"),
    ("phase-1", "fef2c0", "Phase 1: control plane on amd64"),
    ("phase-2", "fef2c0", "Phase 2: shadow, control plane, mode 1"),
    ("phase-3", "fef2c0", "Phase 3: zero-copy mode 2 (optional)"),
    ("phase-4", "fef2c0", "Phase 4: hardening and acceptance"),
    ("env:desk", "c2e0c6", "Done-when needs only this repository"),
    ("env:build-host", "bfd4f2", "Done-when needs the OpenBSD build host"),
    ("env:board", "f9d0c4", "Done-when needs the USG-3P board and bench"),
    ("optional", "d4c5f9", "Only if measurements justify it"),
    ("deferred", "cccccc", "Out of scope for this release"),
]

issues = []
issues.append(issue("C1", "Move work tracking to GitHub Issues; retire TASKS.md and JOURNAL.md",
                    ["chore", "documentation", "env:desk"], C1_BODY, parent="E-INFRA"))
issues.append(issue("ROADMAP", "Roadmap: USG-3P IPv4 fast path (start here)", ["roadmap"], roadmap_body(), pin=True))
for k in ("E-P0", "E-P1", "E-P2", "E-P3", "E-P4"):
    issues.append(issue(k, EPICS[k][0], EPICS[k][1], epic_body(k), parent="ROADMAP"))
issues.append(issue("E-REQ", "Epic: Requirements R1–R16 as user stories", ["epic"], req_epic_body(), parent="ROADMAP"))
issues.append(issue("E-INFRA", "Epic: Project infrastructure, tracking and tooling", ["epic", "chore"], INFRA_BODY, parent="ROADMAP"))
issues.append(issue("C2", "Provision the OpenBSD build host (-current at the pinned commit)",
                    ["chore", "needs-owner", "env:build-host", "phase-0", "phase-1"], C2_BODY, parent="E-INFRA"))
issues.append(issue("C3", "Decide where the OpenBSD src fork lives",
                    ["chore", "needs-owner"], C3_BODY, parent="E-INFRA"))
issues.append(issue("C4", "Update the saved doc-review workflow to revision 5",
                    ["chore", "env:desk"], C4_BODY, parent="E-INFRA"))

for key_list, phase in ((P0, 0), (P1, 1), (P2, 2), (P3, 3), (P4, 4)):
    for k in key_list:
        if k.startswith("G"):
            issues.append(issue(k, GATE_TITLES[k], ["gate", f"phase-{phase}", "env:board"], gate_body(k),
                                parent=EPIC_OF[phase], blocked_by=BLOCKED.get(k)))
        else:
            labels = ["task", f"phase-{phase}"] + ENV[k] + (["optional"] if phase == 3 else [])
            issues.append(issue(k, TITLES[k], labels, task_body(k), parent=EPIC_OF[phase],
                                blocked_by=BLOCKED.get(k)))

for r in STORY_ORDER:
    prio, short = STORY[r][0], STORY[r][1]
    title = f"{r if r != 'MODEP' else 'Mode P'}: {short}"
    labels = ["user-story"] + (["deferred"] if r in ("R15", "MODEP") else [])
    closed = r in ("R15", "MODEP")
    issues.append(issue(r, title, labels, story_body(r), parent="E-REQ",
                        state="closed" if closed else "open",
                        state_reason="not_planned" if closed else None))

db = {
    "repo": REPO,
    "description": "CPU-assisted IPv4 fast path for the OpenBSD/octeon cnmac(4) driver on a Ubiquiti USG-3P: spec, design, decision record and work tracking",
    "baseline": BASE,
    "labels": [{"name": n, "color": c, "description": d} for n, c, d in LABELS],
    "issues": issues,
}
# Keep everything track.py has recorded since the first generation.
if OUT.exists():
    old = {i["key"]: i for i in json.loads(OUT.read_text(encoding="utf-8"))["issues"]}
    for i in issues:
        o = old.get(i["key"])
        if not o:
            continue
        for f in ("comments", "number", "id", "body_synced", "parent_linked",
                  "blocked_linked", "state_synced", "pinned", "state", "state_reason"):
            if f in o:
                i[f] = o[f]
        if o.get("number") and o.get("body") != i["body"]:
            i["body_synced"] = False
    db["dependencies_unsupported"] = json.loads(OUT.read_text(encoding="utf-8")).get("dependencies_unsupported", False)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(db, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT} with {len(issues)} issues")
