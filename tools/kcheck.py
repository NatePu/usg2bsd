#!/usr/bin/env python3
"""Syntax-check OpenBSD amd64 GENERIC.MP kernel sources with clang, on any host.

    tools/kcheck.py [--src DIR] [--no-flow] [--keep-going] FILE...

FILE paths are relative to the tree (e.g. sys/net/if_flow.c) or absolute.
This is a pre-build sanity check for the development Mac: it emulates what
config(8) gives the compiler (needs-flag/needs-count headers, option -D
flags, the machine/ include link) and runs `clang -fsyntax-only` with the
amd64 kernel warning flags and -Werror. It does not link, assemble, run
config(8) or check octeon (Apple clang has no MIPS backend). The OpenBSD
build host stays the gate for every Done-when (AGENTS.md).

--no-flow checks as if `pseudo-device flow` were absent (NFLOW 0).
Generated headers go to <repo>/.kcheck/amd64 (gitignored).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = "x86_64-unknown-openbsd"

# Flags from sys/arch/amd64/conf/Makefile.amd64 at the fork point, minus the
# OpenBSD-only ones other clangs reject (-msave-args, -fret-clean) and the
# retpoline/CET code-generation flags that do not affect syntax.
CWARN = ["-Werror", "-Wall", "-Wimplicit-function-declaration", "-Wno-pointer-sign",
         "-Wframe-larger-than=2047", "-Wno-address-of-packed-member",
         "-Wno-constant-conversion", "-Wno-unused-but-set-variable",
         "-Wno-gnu-folding-constant"]
CMACH = ["-mcmodel=kernel", "-mno-red-zone", "-mno-sse2", "-mno-sse", "-mno-3dnow",
         "-mno-mmx", "-msoft-float", "-fno-omit-frame-pointer", "-ffreestanding",
         "-fno-pie"]
# Warnings newer than the fork point's base clang, which unmodified sources
# trip; kept off so -Werror only reports what the build host would.
NEWER_CLANG = ["-Wno-unknown-warning-option", "-Wno-default-const-init-unsafe",
               "-Wno-default-const-init-field-unsafe",
               "-Wno-unterminated-string-initialization"]
PARAM = ["-DHZ=100", "-DTIMEZONE=0", "-DDST=0", "-DMAXUSERS=80"]
CONFIGS = ["sys/conf/GENERIC", "sys/arch/amd64/conf/GENERIC", "sys/arch/amd64/conf/GENERIC.MP"]
FILES = ["sys/conf/files", "sys/arch/amd64/conf/files.amd64"]


def strip_comment(line):
    return line.split("#", 1)[0].strip()


def config_state(src):
    """Options (-D flags) and configured device names/counts from GENERIC.MP."""
    opts, devs = [], {}
    for cf in CONFIGS:
        for raw in (src / cf).read_text().splitlines():
            line = strip_comment(raw)
            if not line:
                continue
            words = line.split()
            if words[0] == "option" and len(words) > 1:
                for o in " ".join(words[1:]).split(","):
                    o = o.strip()
                    if o:
                        opts.append(f"-D{o}")
            elif words[0] == "pseudo-device" and len(words) > 1:
                count = int(words[2]) if len(words) > 2 and words[2].isdigit() else 1
                devs[words[1]] = devs.get(words[1], 0) + count
            elif len(words) > 2 and words[1] == "at":
                name = re.sub(r"[0-9*]+$", "", words[0])
                devs[name] = devs.get(name, 0) + 1
    return opts, devs


def needs_headers(src):
    """Names whose <name>.h config(8) generates (needs-flag / needs-count)."""
    names = set()
    for f in FILES:
        for raw in (src / f).read_text().splitlines():
            line = strip_comment(raw)
            if not line.startswith("file") or "needs-" not in line:
                continue
            m = re.match(r"^file\s+\S+\s+(.*?)\s+needs-(?:flag|count)", line)
            if not m:
                continue
            for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", m.group(1)):
                if word not in ("and", "or", "not"):
                    names.add(word)
    return names


def prepare(src, flow):
    obj = ROOT / ".kcheck" / "amd64"
    if obj.exists():
        shutil.rmtree(obj)
    obj.mkdir(parents=True)
    opts, devs = config_state(src)
    if not flow:
        devs.pop("flow", None)
    for name in sorted(needs_headers(src) | {"flow"}):
        count = devs.get(name, 0)
        (obj / f"{name}.h").write_text(f"#define N{name.upper()} {count}\n")
    (obj / "machine").symlink_to(src / "sys/arch/amd64/include")
    (obj / "amd64").symlink_to(src / "sys/arch/amd64/include")
    return obj, opts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=str(ROOT / "src"))
    ap.add_argument("--no-flow", action="store_true")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    src = Path(a.src).resolve()
    obj, opts = prepare(src, flow=not a.no_flow)
    s = src / "sys"
    base = ["clang", "-target", TARGET, "-fsyntax-only", "-nostdinc", f"-I{s}", f"-I{obj}",
            f"-I{s}/arch", "-D_KERNEL"] + opts + PARAM + CWARN + CMACH + NEWER_CLANG
    failed = 0
    for f in a.files:
        path = Path(f) if os.path.isabs(f) else src / f
        p = subprocess.run(base + [str(path)], capture_output=True, text=True)
        status = "ok" if p.returncode == 0 else "FAIL"
        print(f"{status:4} {f}")
        if p.returncode:
            failed += 1
            sys.stdout.write(p.stderr)
            if not a.keep_going:
                break
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
