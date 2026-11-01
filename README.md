# usg2bsd

A CPU-assisted IPv4 fast path for the OpenBSD/octeon `cnmac(4)` driver on the
Ubiquiti UniFi Security Gateway 3P (USG-3P). It is a lab fork of OpenBSD
-current for that one box: not for production, and not meant for upstream.

The USG-3P has a Cavium CN5020: two 500 MHz cnMIPS64 cores, three RGMII ports
and no flow engine. On stock OpenBSD one forwarded flow saturates a core in
softnet. The fork adds a fast path to the `cnmac(4)` receive interrupt: when a
packet belongs to a destination pair the kernel has already routed, the fast
path rewrites its Ethernet header and TTL and hands it straight to the egress
port's transmit queue, skipping softnet, `ip_input`, `ip_forward` and the route
lookup. Any routing, ARP, interface, VLAN, pf or IPsec change invalidates what
it learned. The scope is IPv4 only, without NAT: static routes, OSPF routes and
VLANs ([SPEC §1](docs/SPEC.md#1-purpose)).

## Status

Phase 1, the control plane on amd64, is under way. The build integration, the
`net.flow` sysctls, the flow table and the invalidation hooks (T1.0–T1.3) are
written and pass every check that runs on macOS, but nothing has been built or
booted on OpenBSD yet: that needs the build host ([#10](https://github.com/NatePu/usg2bsd/issues/10)). The bench
configuration and scripts for the Phase 0 measurements are written (T0.3) but
not yet run on the bench.

## Work tracking

[GitHub Issues](https://github.com/NatePu/usg2bsd/issues) are the source of
truth for all work: the plan, status, findings and the log of every step,
checkpointed in each issue. Start at the pinned
[roadmap](https://github.com/NatePu/usg2bsd/issues/2). Each phase is
an epic whose sub-issues are its tasks (T\*) and gates (G\*); the requirements
(R\*) are user stories, and discrepancies are findings (F\*). Rules for people
and agents: [AGENTS.md](AGENTS.md).

## Layout

| Path | Contents |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | Requirements (R\*), behaviour contract, acceptance gates (G\*). Authoritative. |
| [`docs/ERRATA.md`](docs/ERRATA.md) | Binding decisions (D\*) and errata (E\*); what changed and why. |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Architecture: data structures, locking, hooks, mode switching. |
| [`docs/NOTES.md`](docs/NOTES.md) | Source facts at the fork point and results. |
| [`docs/STOCK_TEST_PLAN.md`](docs/STOCK_TEST_PLAN.md) | Stock-kernel baseline procedure (gate G0). |
| [`patches/`](patches) | The fork: a patch series against OpenBSD -current `c595b86dd344`. |
| [`tools/`](tools) | Recreate the fork tree, regenerate the patches, run the macOS checks, sync the project board. |
| [`tests/`](tests) | Acceptance scripts for the test VM, and a host harness for `if_flow.c`. |
| [`bench/`](bench) | Bench topology, router configuration, traffic and measurement scripts. |

## Building

```sh
tools/fork-src.sh                  # OpenBSD src at the fork point plus patches/, in src/
FULL=1 tools/fork-src.sh /usr/src  # a full tree, on the OpenBSD build host
tools/desk-check.sh                # every check that runs on macOS
```

The kernel builds on OpenBSD only (`config GENERIC.MP` with `pseudo-device
flow`). `tools/desk-check.sh` checks syntax with clang and the amd64 kernel
flags, runs OpenBSD's `config(8)` for amd64 and octeon, checks `sysctl(8)`,
and runs the real `if_flow.c` in a host harness. None of this replaces a build
and boot on OpenBSD. To change the fork, commit in `src/` on branch `usg2bsd`,
run `tools/fork-patches.sh`, and commit `patches/` here.

## License

Not chosen yet ([#79](https://github.com/NatePu/usg2bsd/issues/79)). The new kernel files carry the ISC license, as
OpenBSD code does. Modified OpenBSD files keep their own licenses.
