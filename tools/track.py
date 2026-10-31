#!/usr/bin/env python3
"""Stage, check and publish this project's GitHub issues.

GitHub Issues are the source of truth for all work on this project
(AGENTS.md). Until the repository exists on GitHub, the issues and every
checkpoint comment are staged in tracking/issues.json. `publish` creates the
private repository (if missing), pushes main, and creates the labels, issues,
sub-issue links, "blocked by" links, queued comments, closures and the pinned
roadmap. It records each GitHub number as it goes, so it is safe to re-run
after a failure: finished steps are skipped.

Usage:
  tools/track.py check                       validate the staged issues
  tools/track.py list [--label L] [--open]   key, number, state, title
  tools/track.py show KEY                    print the resolved body
  tools/track.py comment KEY [-m TEXT | -F FILE] [--author NAME]
                                             queue a timestamped checkpoint
                                             (text from stdin without -m/-F)
  tools/track.py state KEY open|closed [--reason completed|not_planned]
  tools/track.py new KEY --title T --labels a,b [--parent P] [--blocked-by X,Y]
                     [-m TEXT | -F FILE]  stage a new issue (e.g. a finding)
  tools/track.py publish [--dry-run]         create everything on GitHub

Body placeholders, resolved when shown or published:
  {{KEY}}              issue reference, e.g. {{T1.2}} -> #24
  {{REPO_URL}}         https://github.com/OWNER/NAME
  {{DOC:DESIGN:5.3}}   link to a numbered section of docs/DESIGN.md (current
                       headings; appendices are A, B)
  {{BASELINE:path}}    permalink to path at the baseline commit
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tracking" / "issues.json"
DEFAULT_AUTHOR = "Claude Code (Opus 5.5)"
GITHUB_DEFAULT_LABELS = {
    "bug", "documentation", "duplicate", "enhancement", "good first issue",
    "help wanted", "invalid", "question", "wontfix",
}
PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_.:/\-]+)\}\}")
MAX_BODY = 65536
# GitHub allows about 80 content-creating requests a minute; publish makes
# several hundred, so pace them and wait out a secondary rate limit.
WRITE_DELAY = float(os.environ.get("TRACK_DELAY", "1.0"))
RATE_RETRIES = 6


def die(msg):
    print(f"track.py: {msg}", file=sys.stderr)
    sys.exit(1)


def load():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


def save(db):
    # Write atomically so an interrupted publish never truncates the file.
    fd, tmp = tempfile.mkstemp(dir=DATA.parent, prefix=".issues.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, DATA)


def by_key(db):
    return {i["key"]: i for i in db["issues"]}


def get_issue(db, key):
    issue = by_key(db).get(key)
    if issue is None:
        die(f"no issue with key {key!r}")
    return issue


def now_stamp():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


# --- documentation anchors -------------------------------------------------

def gh_slug(text):
    """GitHub heading anchor: lower case, drop punctuation and symbols,
    keep letters, digits, spaces, '-' and '_', spaces become '-'."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    out = []
    for ch in text.strip().lower():
        if ch in " -_" or unicodedata.category(ch)[0] in "LNM":
            out.append(ch)
    return "".join(out).replace(" ", "-")


def doc_sections(doc):
    """Map section ids ("5.3", "7", "A") to anchors for docs/<doc>.md."""
    path = ROOT / "docs" / f"{doc}.md"
    if not path.exists():
        return None
    sections, fence = {}, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fence = not fence
            continue
        m = None if fence else re.match(r"^#{1,6}\s+(.*?)\s*$", line)
        if not m:
            continue
        heading = m.group(1)
        sm = re.match(r"^(?:Appendix\s+([A-Z])\b|(\d+(?:\.\d+)*)\.?\s)", heading)
        if sm:
            sections.setdefault(sm.group(1) or sm.group(2), gh_slug(heading))
    return sections


# --- placeholder resolution -------------------------------------------------

def resolve(db, text, strict=False, errors=None):
    keys = by_key(db)
    repo_url = f"https://github.com/{db['repo']}"
    cache = {}

    def sub(m):
        token = m.group(1)
        if token == "REPO_URL":
            return repo_url
        if token.startswith("DOC:"):
            parts = token.split(":")
            if len(parts) != 3:
                (errors is not None) and errors.append(f"bad DOC token {token}")
                return token
            doc, sec = parts[1], parts[2]
            if doc not in cache:
                cache[doc] = doc_sections(doc)
            secs = cache[doc]
            base = f"{repo_url}/blob/main/docs/{doc}.md"
            if secs is None:
                (errors is not None) and errors.append(f"missing doc {doc}.md")
                return base
            if sec not in secs:
                (errors is not None) and errors.append(f"no section {sec} in {doc}.md")
                return base
            return f"{base}#{secs[sec]}"
        if token.startswith("BASELINE:"):
            path = token[len("BASELINE:"):]
            return f"{repo_url}/blob/{db['baseline']}/{path}"
        if token in keys:
            num = keys[token].get("number")
            return f"#{num}" if num else f"#?{token}"
        if errors is not None:
            errors.append(f"unknown placeholder {{{{{token}}}}}")
        return m.group(0)

    return PLACEHOLDER.sub(sub, text)


# --- check ------------------------------------------------------------------

def cmd_check(db, quiet=False):
    errors = []
    keys = by_key(db)
    if len(keys) != len(db["issues"]):
        seen = set()
        for i in db["issues"]:
            if i["key"] in seen:
                errors.append(f"duplicate key {i['key']}")
            seen.add(i["key"])
    defined = {l["name"] for l in db["labels"]} | GITHUB_DEFAULT_LABELS
    children = {}
    for i in db["issues"]:
        k = i["key"]
        if not i.get("title") or len(i["title"]) > 256:
            errors.append(f"{k}: title missing or longer than 256 characters")
        for l in i.get("labels", []):
            if l not in defined:
                errors.append(f"{k}: undefined label {l!r}")
        p = i.get("parent")
        if p:
            if p not in keys:
                errors.append(f"{k}: unknown parent {p}")
            children.setdefault(p, []).append(k)
        for b in i.get("blocked_by", []):
            if b not in keys:
                errors.append(f"{k}: unknown blocker {b}")
            if b == k:
                errors.append(f"{k}: blocked by itself")
        if i.get("state") not in ("open", "closed"):
            errors.append(f"{k}: state must be open or closed")
        if i.get("state") == "closed" and i.get("state_reason") not in ("completed", "not_planned"):
            errors.append(f"{k}: closed without state_reason")
        errs = []
        body = resolve(db, i.get("body", ""), errors=errs)
        errors.extend(f"{k}: {e}" for e in errs)
        if len(body) > MAX_BODY:
            errors.append(f"{k}: body has {len(body)} characters (max {MAX_BODY})")
        for c in i.get("comments", []):
            errs = []
            resolve(db, c["body"], errors=errs)
            errors.extend(f"{k} comment {c['at']}: {e}" for e in errs)
    for p, cs in children.items():
        if len(cs) > 100:
            errors.append(f"{p}: {len(cs)} sub-issues (GitHub allows 100)")
    # Parent chains must be acyclic, and so must "blocked by".
    for start in keys:
        seen, k = set(), start
        while k:
            if k in seen:
                errors.append(f"parent cycle through {start}")
                break
            seen.add(k)
            k = keys[k].get("parent") if k in keys else None
    state = {}

    def visit(k, stack):
        if state.get(k) == 1:
            errors.append("blocked-by cycle: " + " -> ".join(stack + [k]))
            return
        if state.get(k) == 2:
            return
        state[k] = 1
        for b in keys[k].get("blocked_by", []):
            if b in keys:
                visit(b, stack + [k])
        state[k] = 2

    for k in keys:
        visit(k, [])
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        die(f"{len(errors)} problem(s)")
    if not quiet:
        n_open = sum(1 for i in db["issues"] if i["state"] == "open")
        n_com = sum(len(i.get("comments", [])) for i in db["issues"])
        n_pub = sum(1 for i in db["issues"] if i.get("number"))
        print(f"ok: {len(db['issues'])} issues ({n_open} open), "
              f"{n_com} comments, {len(db['labels'])} labels, "
              f"{n_pub} published, repo {db['repo']}")


# --- simple commands ----------------------------------------------------------

def cmd_list(db, label=None, only_open=False):
    for i in db["issues"]:
        if label and label not in i.get("labels", []):
            continue
        if only_open and i["state"] != "open":
            continue
        num = f"#{i['number']}" if i.get("number") else "-"
        print(f"{i['key']:<8} {num:<6} {i['state']:<6} {i['title']}")


def cmd_show(db, key):
    i = get_issue(db, key)
    print(f"# {i['title']}")
    print(f"labels: {', '.join(i.get('labels', []))}")
    print(f"parent: {i.get('parent')}  blocked by: {', '.join(i.get('blocked_by', [])) or '-'}")
    print(f"state: {i['state']} {i.get('state_reason') or ''}")
    print()
    print(resolve(db, i.get("body", "")))
    for c in i.get("comments", []):
        print("\n---\n" + render_comment(db, c))


def render_comment(db, c):
    head = f"**Checkpoint** · {c['at']} · {c['author']}"
    text = resolve(db, c["body"])
    if c.get("queued"):
        text += ("\n\n<sub>Queued locally while the GitHub repository did not "
                 "exist yet; the time above is when the work was done.</sub>")
    return f"{head}\n\n{text}"


def cmd_comment(db, key, text, author):
    i = get_issue(db, key)
    if not text.strip():
        die("empty comment")
    c = {"at": now_stamp(), "author": author, "body": text.strip(),
         "queued": not i.get("number"), "posted": False}
    i.setdefault("comments", []).append(c)
    errs = []
    resolve(db, c["body"], errors=errs)
    if errs:
        die("; ".join(errs))
    save(db)
    print(f"queued comment on {key} at {c['at']}")


def cmd_new(db, key, title, labels, parent, blocked_by, body):
    if key in by_key(db):
        die(f"key {key} exists")
    issue = {"key": key, "title": title, "labels": labels, "body": body.strip() + "\n",
             "parent": parent, "blocked_by": blocked_by, "state": "open", "state_reason": None,
             "pin": False, "comments": [], "number": None}
    db["issues"].append(issue)
    cmd_check(db, quiet=True)
    save(db)
    print(f"staged {key}: {title}")


def cmd_state(db, key, state, reason):
    i = get_issue(db, key)
    i["state"] = state
    i["state_reason"] = (reason or "completed") if state == "closed" else None
    i["state_synced"] = False
    save(db)
    print(f"{key}: {state} {i['state_reason'] or ''}")


# --- publish ------------------------------------------------------------------

class GH:
    def __init__(self, repo, dry):
        self.repo, self.dry = repo, dry

    def run(self, args, payload=None, ok_codes=(0,)):
        if self.dry:
            print("DRY:", " ".join(args))
            return {}
        for attempt in range(RATE_RETRIES):
            p = subprocess.run(["gh"] + args, input=json.dumps(payload) if payload is not None else None,
                               capture_output=True, text=True)
            time.sleep(WRITE_DELAY)
            # Only a rate-limit refusal is retried: the request was rejected,
            # so repeating it cannot create anything twice.
            if p.returncode in ok_codes or "rate limit" not in p.stderr.lower():
                break
            wait = 60 * (attempt + 1)
            print(f"rate limited; waiting {wait}s", file=sys.stderr, flush=True)
            time.sleep(wait)
        if p.returncode not in ok_codes:
            raise RuntimeError(f"gh {' '.join(args)} failed ({p.returncode}): {p.stderr.strip()}")
        out = p.stdout.strip()
        try:
            return json.loads(out) if out else {}
        except json.JSONDecodeError:
            return {"raw": out}

    def api(self, method, path, payload=None):
        args = ["api", "-X", method, f"repos/{self.repo}/{path}"]
        if payload is not None:
            args += ["--input", "-"]
        return self.run(args, payload)


def ensure_repo(db, dry):
    repo = db["repo"]
    exists = subprocess.run(["gh", "repo", "view", repo, "--json", "name"],
                            capture_output=True, text=True).returncode == 0
    if not exists:
        print(f"creating private repository {repo}")
        if not dry:
            p = subprocess.run(["gh", "repo", "create", repo, "--private",
                                "--description", db["description"]],
                               capture_output=True, text=True)
            if p.returncode != 0:
                die(f"gh repo create failed: {p.stderr.strip()}")
    url = f"https://github.com/{repo}.git"
    remotes = subprocess.run(["git", "-C", str(ROOT), "remote"], capture_output=True, text=True).stdout.split()
    if "origin" not in remotes:
        print(f"adding remote origin {url}")
        if not dry:
            subprocess.run(["git", "-C", str(ROOT), "remote", "add", "origin", url], check=True)
    print("pushing main")
    if not dry:
        subprocess.run(["git", "-C", str(ROOT), "push", "-u", "origin", "main"], check=True)


def cmd_publish(db, dry):
    cmd_check(db, quiet=True)
    gh = GH(db["repo"], dry)
    ensure_repo(db, dry)
    for l in db["labels"]:
        gh.run(["label", "create", l["name"], "--repo", db["repo"], "--color", l["color"],
                "--description", l["description"], "--force"])
    issues = db["issues"]
    # 1. Create every issue first, so all numbers exist before bodies refer to them.
    for i in issues:
        if i.get("number"):
            continue
        res = gh.api("POST", "issues", {"title": i["title"], "labels": i.get("labels", []),
                                        "body": "_Publishing; the full text follows in a moment._"})
        if dry:
            continue
        i["number"], i["id"] = res["number"], res["id"]
        i["body_synced"] = False
        save(db)
        print(f"created #{i['number']} {i['key']}")
    # 2. Bodies with resolved references.
    for i in issues:
        if i.get("body_synced") or dry and not i.get("number"):
            continue
        gh.api("PATCH", f"issues/{i['number']}", {"body": resolve(db, i.get("body", ""))})
        if not dry:
            i["body_synced"] = True
            save(db)
    keys = by_key(db)
    # 3. Sub-issues (parent epics, roadmap).
    for i in issues:
        p = i.get("parent")
        if not p or i.get("parent_linked") or dry:
            continue
        try:
            gh.api("POST", f"issues/{keys[p]['number']}/sub_issues", {"sub_issue_id": i["id"]})
        except RuntimeError as e:
            if "already" not in str(e).lower():
                raise
        i["parent_linked"] = True
        save(db)
    # 4. "Blocked by" links; the text in each body already lists them.
    if not db.get("dependencies_unsupported"):
        for i in issues:
            for b in i.get("blocked_by", []):
                done = i.setdefault("blocked_linked", [])
                if b in done or dry:
                    continue
                try:
                    gh.api("POST", f"issues/{i['number']}/dependencies/blocked_by",
                           {"issue_id": keys[b]["id"]})
                except RuntimeError as e:
                    msg = str(e).lower()
                    if "404" in msg or "not found" in msg:
                        print("note: issue dependencies API unavailable; bodies list blockers")
                        db["dependencies_unsupported"] = True
                        save(db)
                        break
                    if "already" not in msg:
                        raise
                done.append(b)
                save(db)
            if db.get("dependencies_unsupported"):
                break
    # 5. Queued checkpoint comments, oldest first.
    for i in issues:
        for c in i.get("comments", []):
            if c.get("posted") or dry:
                continue
            gh.api("POST", f"issues/{i['number']}/comments", {"body": render_comment(db, c)})
            c["posted"] = True
            save(db)
    # 6. Closed issues.
    for i in issues:
        if i["state"] == "closed" and not i.get("state_synced") and not dry:
            gh.api("PATCH", f"issues/{i['number']}",
                   {"state": "closed", "state_reason": i.get("state_reason", "completed")})
            i["state_synced"] = True
            save(db)
    # 7. Pin the roadmap.
    for i in issues:
        if i.get("pin") and not i.get("pinned") and not dry:
            gh.run(["issue", "pin", str(i["number"]), "--repo", db["repo"]])
            i["pinned"] = True
            save(db)
    if dry:
        print(f"dry run: would publish {len(issues)} issues to {db['repo']}")
    else:
        road = next((i for i in issues if i.get("pin")), None)
        print(f"published {len(issues)} issues to https://github.com/{db['repo']}/issues"
              + (f" (roadmap #{road['number']})" if road else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("check")
    p = sp.add_parser("list")
    p.add_argument("--label")
    p.add_argument("--open", action="store_true")
    p = sp.add_parser("show")
    p.add_argument("key")
    p = sp.add_parser("comment")
    p.add_argument("key")
    p.add_argument("-m", "--message")
    p.add_argument("-F", "--file")
    p.add_argument("--author", default=DEFAULT_AUTHOR)
    p = sp.add_parser("state")
    p.add_argument("key")
    p.add_argument("state", choices=["open", "closed"])
    p.add_argument("--reason", choices=["completed", "not_planned"])
    p = sp.add_parser("new")
    p.add_argument("key")
    p.add_argument("--title", required=True)
    p.add_argument("--labels", default="")
    p.add_argument("--parent")
    p.add_argument("--blocked-by", default="")
    p.add_argument("-m", "--message")
    p.add_argument("-F", "--file")
    p = sp.add_parser("publish")
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    db = load()
    if a.cmd == "check":
        cmd_check(db)
    elif a.cmd == "list":
        cmd_list(db, a.label, a.open)
    elif a.cmd == "show":
        cmd_show(db, a.key)
    elif a.cmd == "comment":
        if a.message is not None:
            text = a.message
        elif a.file:
            text = Path(a.file).read_text(encoding="utf-8")
        else:
            text = sys.stdin.read()
        cmd_comment(db, a.key, text, a.author)
    elif a.cmd == "new":
        body = a.message if a.message is not None else Path(a.file).read_text(encoding="utf-8")
        cmd_new(db, a.key, a.title, [l for l in a.labels.split(",") if l], a.parent,
                [b for b in a.blocked_by.split(",") if b], body)
    elif a.cmd == "state":
        cmd_state(db, a.key, a.state, a.reason)
    elif a.cmd == "publish":
        cmd_publish(db, a.dry_run)


if __name__ == "__main__":
    main()
