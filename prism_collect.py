#!/usr/bin/env python3
"""PRism collector: gather the mechanical facts about a GitHub PR as JSON.

Usage:
    python3 prism_collect.py <PR number or URL> [--repo OWNER/REPO] [--since SHA|last]
                             [--max-nodes 10] [--no-overlaps] [--no-real-check] [--save FILE]
    python3 prism_collect.py --branch [--base NAME] [--uncommitted] [--save FILE]
    python3 prism_collect.py --fill-files PAGE.html FILE

It shells out to the GitHub CLI (`gh`) and `git`, and prints one JSON object to
stdout: PR metadata, every changed file with its flags, map modules, totals,
tests, conflicts (a real `git merge-tree` check when run in a local clone,
file overlap otherwise), and the risk score with itemized reasons.
--since limits the files to what changed since a commit or your last review.
--branch is author mode: your current branch against its base, before a PR exists.
With --save FILE the full JSON goes to FILE and stdout skips the long
"files" and "files_json" keys. --fill-files puts files_json from a saved run
into a page's {{FILES_JSON}} placeholder.
The SKILL.md rubric is implemented here; this file is the source of truth.

Standard library only. It never reads tokens itself; `gh` handles auth.

Exit codes: 0 ok, 2 gh missing, 3 gh not logged in, 4 bad input or PR not
found, 5 other gh error. On error, stdout is {"ok": false, "error": ..., "message": ...}.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import OrderedDict

# --------------------------------------------------------------------------
# Classification rules (SKILL.md step 5 describes these in plain words)
# --------------------------------------------------------------------------

LOCKFILES = {
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "bun.lock", "bun.lockb", "deno.lock", "cargo.lock", "poetry.lock",
    "pipfile.lock", "uv.lock", "pdm.lock", "gemfile.lock", "composer.lock",
    "go.sum", "go.work.sum", "flake.lock", "mix.lock", "pubspec.lock",
    "podfile.lock", "package.resolved", "packages.lock.json",
    "gradle.lockfile", "conan.lock",
}
GENERATED_DIRS = {"dist", "build", "generated", "__generated__", "vendor"}

DEP_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "pipfile", "go.mod", "go.work", "cargo.toml", "gemfile",
    "composer.json", "pom.xml", "build.gradle", "build.gradle.kts",
    "podfile", "package.swift", "pubspec.yaml", "mix.exs", "packages.config",
    "environment.yml", "environment.yaml", "deno.json", "bower.json",
    "vcpkg.json", "conanfile.txt", "conanfile.py", "directory.packages.props",
}
DEP_RE = re.compile(r"(^requirements[-_.][\w.-]*\.txt$|\.gemspec$|\.csproj$|\.fsproj$|\.cabal$)")

TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testdata",
             "test_data", "e2e", "__mocks__", "testing"}
TEST_RE = re.compile(
    r"(^test_.*\.py$|^conftest\.py$|_test\.[a-z0-9]+$|\.(test|spec)\.[a-z0-9]+$"
    r"|_spec\.rb$|(Test|Tests|Spec)\.(java|kt|kts|cs|swift|scala|php|groovy)$)"
)

DOC_EXTS = {".md", ".mdx", ".rst", ".adoc", ".txt"}
DOC_DIRS = {"docs", "doc", "documentation"}
# Files that are data, config, docs or assets rather than program code.
NON_CODE_EXTS = DOC_EXTS | {
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".lock", ".csv", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".webp", ".lottie", ".xml", ".properties", ".editorconfig",
}

SECURITY_WORDS = {
    "auth", "oauth", "oauth2", "authn", "authz", "login", "logout", "signin",
    "signon", "sso", "saml", "oidc", "jwt", "jwks", "session", "sessions",
    "password", "passwords", "passwd", "security", "permission",
    "permissions", "perms", "acl", "acls", "rbac", "crypto", "encrypt",
    "encryption", "decrypt", "secret", "secrets", "credential",
    "credentials", "creds", "token", "tokens", "csrf", "cors", "keyring",
    "keychain", "2fa", "mfa", "totp",
}
SECURITY_PREFIXES = ("authenticat", "authoriz")
MIGRATION_WORDS = {"migration", "migrations", "migrate", "migrator",
                   "alembic", "flyway", "liquibase"}
SCHEMA_FILES = {"schema.prisma", "schema.sql", "structure.sql", "schema.rb",
                "schema.graphql"}
CONFIG_WORDS = {"config", "configs", "configuration", "settings", "conf",
                "k8s", "kubernetes", "helm", "terraform"}
CI_DIRS = (".github/workflows/", ".github/actions/", ".circleci/", ".buildkite/")
CI_FILES = {".gitlab-ci.yml", ".travis.yml", "jenkinsfile", "azure-pipelines.yml",
            "bitbucket-pipelines.yml", "appveyor.yml", ".drone.yml",
            "cloudbuild.yaml", "cloudbuild.yml"}
PAYMENT_WORDS = {"payment", "payments", "billing", "invoice", "invoices",
                 "checkout", "stripe", "paypal", "braintree", "subscription",
                 "subscriptions", "refund", "refunds"}

MERMAID_RESERVED = {"END", "GRAPH", "SUBGRAPH", "CLICK", "CLASS", "CLASSDEF",
                    "STYLE", "LINKSTYLE", "FLOWCHART", "DIRECTION", "CALL",
                    "HEAD", "BASE", "PATH", "GEN", "TESTS", "DEPS", "OTHER"}

STATUS_EMOJI = {"added": "🟢", "modified": "🟡", "deleted": "🔴", "tests": "🧪",
                "deps": "📦", "risky": "🔥", "generated": "🤖"}


def words(path):
    """Split a path into lowercase words (folders, file name parts, camelCase)."""
    out = []
    for part in re.split(r"[/._\-\s]+", path):
        if not part:
            continue
        pieces = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+[a-z]*", part)
        out.extend(p.lower() for p in (pieces or [part]))
        out.append(part.lower())
    return out


def ext_of(name):
    i = name.rfind(".")
    return name[i:].lower() if i > 0 else ""


def is_generated(path):
    segs = path.split("/")
    base = segs[-1].lower()
    if base in LOCKFILES or base.endswith(".lock") or base.endswith(".snap"):
        return True
    if ".min." in base:
        return True
    if any(s.lower() in GENERATED_DIRS for s in segs[:-1]):
        return True
    if "__snapshots__" in segs[:-1]:
        return True
    # migration / schema snapshots, e.g. drizzle/meta/0001_snapshot.json
    if "snapshot" in base and ext_of(base) in {".json", ".yaml", ".yml", ".sql", ".snap"}:
        return True
    return False


def is_test(path):
    segs = path.split("/")
    if any(s.lower() in TEST_DIRS for s in segs[:-1]):
        return True
    return bool(TEST_RE.search(segs[-1]))


def is_deps(path):
    base = path.split("/")[-1].lower()
    return base in DEP_MANIFESTS or bool(DEP_RE.search(base))


def is_doc(path):
    segs = path.split("/")
    return ext_of(segs[-1]) in DOC_EXTS or segs[0].lower() in DOC_DIRS


def risk_kinds(path):
    """Risky areas a (real, non-test, non-doc) file touches."""
    lower = path.lower()
    base = lower.split("/")[-1]
    ws = set(words(path))
    kinds = []
    if ws & SECURITY_WORDS or any(w.startswith(SECURITY_PREFIXES) for w in ws):
        kinds.append("security")
    if (ws & MIGRATION_WORDS or base in SCHEMA_FILES or ext_of(base) == ".prisma"
            or (ext_of(base) == ".sql" and "schema" in ws)):
        kinds.append("migration")
    if lower.startswith(CI_DIRS) or base in CI_FILES:
        kinds.append("ci")
    elif (ws & CONFIG_WORDS or any(w.endswith("config") for w in ws)
          or base.startswith(".env") or base.startswith("dockerfile")
          or base.startswith("docker-compose") or base.startswith("compose.y")
          or ext_of(base) in {".tf", ".tfvars"}
          or (base.startswith(".") and base.endswith("rc"))):
        kinds.append("config")
    if ws & PAYMENT_WORDS:
        kinds.append("payments")
    return kinds


def classify(f):
    """Add flags and a display status to one file dict (path, change, adds, dels)."""
    path = f["path"]
    f["generated"] = is_generated(path)
    f["tests"] = (not f["generated"]) and is_test(path)
    f["deps"] = (not f["generated"]) and (not f["tests"]) and is_deps(path)
    f["doc"] = is_doc(path) and not f["deps"]
    kinds = [] if (f["generated"] or f["tests"] or f["deps"] or f["doc"]) else risk_kinds(path)
    f["risky"] = bool(kinds)
    f["risky_kinds"] = kinds
    f["code"] = (not f["generated"] and not f["tests"] and not f["deps"]
                 and not f["doc"] and ext_of(path.split("/")[-1]) not in NON_CODE_EXTS)
    # Display status. Generated > tests > deps > deleted > risky > added/modified.
    if f["generated"]:
        status = "generated"
    elif f["tests"]:
        status = "tests"
    elif f["deps"]:
        status = "deps"
    elif f["change"] == "deleted":
        status = "deleted"
    elif f["risky"]:
        status = "risky"
    elif f["change"] == "added":
        status = "added"
    else:
        status = "modified"
    f["status"] = status
    return f


# --------------------------------------------------------------------------
# gh helpers
# --------------------------------------------------------------------------

class Fail(Exception):
    def __init__(self, code, error, message, detail=None):
        super().__init__(message)
        self.code, self.error, self.message, self.detail = code, error, message, detail


def gh(args, env=None):
    proc = subprocess.run(["gh"] + args, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr.strip()


def gh_json(args, env, what):
    code, out, err = gh(args, env)
    if code != 0:
        low = err.lower()
        if "could not resolve to a pullrequest" in low or "no pull requests found" in low \
                or "not found" in low:
            raise Fail(4, "pr_not_found", "Could not find that PR: " + what, err)
        if "not a git repository" in low or "none of the git remotes" in low \
                or "could not determine" in low:
            raise Fail(4, "no_repo", "No GitHub repo here. Pass a PR URL or --repo OWNER/REPO.", err)
        if "auth login" in low or "not logged" in low:
            raise Fail(3, "gh_not_logged_in", "gh is not logged in. Run: gh auth login", err)
        raise Fail(5, "gh_error", "gh failed while fetching " + what, err)
    try:
        return json.loads(out)
    except ValueError:
        raise Fail(5, "gh_bad_output", "gh returned output that is not JSON for " + what, out[:500])


def parse_target(target, repo_flag):
    """Return (host, repo or None, number)."""
    host, repo = None, None
    t = target.strip()
    m = re.match(r"^(?:https?://)?([^/\s]+)/([^/\s]+)/([^/\s]+)/pull/(\d+)", t)
    if m:
        host, repo, number = m.group(1), m.group(2) + "/" + m.group(3), int(m.group(4))
    else:
        m = re.match(r"^([\w.-]+/[\w.-]+)#(\d+)$", t)
        if m:
            repo, number = m.group(1), int(m.group(2))
        else:
            m = re.match(r"^#?(\d+)$", t)
            if not m:
                raise Fail(4, "bad_input", "Expected a PR number or URL, got: " + target)
            number = int(m.group(1))
    if repo_flag:
        parts = repo_flag.strip("/").split("/")
        if len(parts) == 3:
            host, repo = parts[0], parts[1] + "/" + parts[2]
        elif len(parts) == 2:
            repo = repo_flag.strip("/")
        else:
            raise Fail(4, "bad_input", "--repo must be OWNER/REPO, got: " + repo_flag)
    return host, repo, number


# --------------------------------------------------------------------------
# Modules for the map
# --------------------------------------------------------------------------

def common_dir(paths):
    dirs = [p.split("/")[:-1] for p in paths]
    prefix = dirs[0]
    for d in dirs[1:]:
        i = 0
        while i < len(prefix) and i < len(d) and prefix[i] == d[i]:
            i += 1
        prefix = prefix[:i]
    return prefix


def split_group(files):
    """Split files by the folder right after their common folder. None if no split."""
    prefix = common_dir([f["path"] for f in files])
    n = len(prefix)
    parts = OrderedDict()
    for f in files:
        segs = f["path"].split("/")
        key = segs[n] if len(segs) > n + 1 else ""  # "" = file directly in prefix
        parts.setdefault(key, []).append(f)
    return list(parts.values()) if len(parts) > 1 else None


def lines(files):
    return sum(f["additions"] + f["deletions"] for f in files)


def build_folder_groups(files, budget):
    """Group by top-level folder, then split big groups deeper while under budget."""
    top = OrderedDict()
    for f in sorted(files, key=lambda x: x["path"]):
        segs = f["path"].split("/")
        top.setdefault(segs[0] if len(segs) > 1 else "", []).append(f)
    groups = list(top.values())
    if len(groups) > budget:
        return groups, True
    changed = True
    while changed and len(groups) < budget:
        changed = False
        for g in sorted(groups, key=lambda g: (-len(g), -lines(g))):
            if len(g) < 2:
                break
            sub = split_group(g)
            if sub and len(groups) - 1 + len(sub) <= budget:
                i = groups.index(g)
                groups[i:i + 1] = sub
                changed = True
                break
    return groups, False


def short_path(segs, limit=32):
    """Full path when short, else the last two parts."""
    full = "/".join(segs)
    return full if len(full) <= limit or len(segs) <= 2 else "/".join(segs[-2:])


def group_label(files):
    if len(files) == 1:
        return short_path(files[0]["path"].split("/"))
    prefix = common_dir([f["path"] for f in files])
    return short_path(prefix) if prefix else "root files"


def mermaid_safe(text):
    """Drop characters that break Mermaid labels, even inside quotes."""
    return re.sub(r"\s+", " ", re.sub(r"[#()\[\]{}\"<>;`|]", " ", text)).strip()


def make_id(label, used):
    name = label.split("/")[-1].lstrip(".")
    name = name.rsplit(".", 1)[0] if "." in name else name
    base = re.sub(r"[^A-Za-z0-9]", "", name).upper()[:10]
    if not base:
        base = "MOD"
    if base[0].isdigit():
        base = "M" + base
    cand, i = base, 2
    while cand in used or cand in MERMAID_RESERVED:
        cand = "%s%d" % (base, i)
        i += 1
    used.add(cand)
    return cand


def module_status(files, kind):
    if kind in ("tests", "deps", "generated"):
        return kind
    if any(f["risky"] and f["change"] != "deleted" for f in files):
        return "risky"
    changes = {f["change"] for f in files}
    if changes == {"deleted"}:
        return "deleted"
    if changes == {"added"}:
        return "added"
    return "modified"


def make_module(mid, label, kind, files):
    adds = sum(f["additions"] for f in files)
    dels = sum(f["deletions"] for f in files)
    status = module_status(files, kind)
    kinds = sorted({k for f in files for k in f["risky_kinds"]})
    if kind == "generated":
        n = len(files)
        label = "auto-generated %d file%s" % (n, "" if n == 1 else "s")
    elif kind == "other":
        label = "other %d files" % len(files)
    return OrderedDict([
        ("id", mid), ("label", label), ("kind", kind), ("status", status),
        ("mermaid_class", status),
        ("node_label", "%s %s +%d/-%d" % (STATUS_EMOJI[status], mermaid_safe(label), adds, dels)),
        ("file_count", len(files)), ("additions", adds), ("deletions", dels),
        ("risky_kinds", kinds), ("on_review_path", kind != "generated"),
        ("files", [f["path"] for f in files]),
    ])


def build_modules(files, max_nodes):
    gen = [f for f in files if f["generated"]]
    tests = [f for f in files if f["tests"]]
    deps = [f for f in files if f["deps"]]
    rest = [f for f in files if not (f["generated"] or f["tests"] or f["deps"])]
    fixed = sum(1 for g in (gen, tests, deps) if g)
    budget = max(1, max_nodes - 2 - fixed)  # 2 = HEAD and BASE branch nodes
    used = set()
    modules = []
    if rest:
        groups, too_many = build_folder_groups(rest, budget)
        other = []
        if too_many:
            groups.sort(key=lambda g: -lines(g))
            keep = max(1, budget - 1)
            other = [f for g in groups[keep:] for f in g]
            groups = sorted(groups[:keep], key=lambda g: g[0]["path"])
        for g in groups:
            label = group_label(g)
            modules.append(make_module(make_id(label, used), label, "folder", g))
        if other:
            used.add("OTHER")
            modules.append(make_module("OTHER", "other", "other", other))
    if tests:
        used.add("TESTS")
        modules.append(make_module("TESTS", "tests", "tests", tests))
    if deps:
        used.add("DEPS")
        label = deps[0]["path"].split("/")[-1] if len(deps) == 1 else "dependencies"
        modules.append(make_module("DEPS", label, "deps", deps))
    if gen:
        used.add("GEN")
        modules.append(make_module("GEN", "auto-generated", "generated", gen))
    by_path = {f["path"]: f for f in files}
    for m in modules:
        for p in m["files"]:
            by_path[p]["module"] = m["id"]
    return modules


# --------------------------------------------------------------------------
# Risk (SKILL.md step 6 describes this rubric in plain words)
# --------------------------------------------------------------------------

# Added lines in a migration patch that change or drop existing data.
MIGRATION_CHANGE_RE = re.compile(
    r"^\+(?!\+\+).*\b(alter\s+table|drop\s+(table|column|index|constraint|view)|rename\s+(to|column)"
    r"|update\s+\w+\s+set|delete\s+from|truncate|remove_column|rename_column|change_column"
    r"|drop_table|drop_column|alter_column|rename_table|change_table|op\.drop_|op\.alter_)",
    re.I | re.M)
MIGRATION_PATCH_RE = r"(?i)migrat|schema|[.]sql$|[.]prisma$"


def sample(paths, n=2):
    s = ", ".join(paths[:n])
    return s + (" (+%d more)" % (len(paths) - n) if len(paths) > n else "")


def tests_summary(files):
    real = [f for f in files if not f["generated"]]
    test_files = [f for f in real if f["tests"]]
    other = [f for f in real if not f["tests"]]
    code_files = [f for f in real if f["code"]]
    code_lines = lines(code_files)
    test_lines = lines(test_files)
    other_lines = lines(other)
    # Skip the test rule for docs/config-only changes and tiny code changes.
    needed = bool(code_files) and code_lines >= 20
    return OrderedDict([
        ("present", bool(test_files)), ("files", len(test_files)),
        ("lines", test_lines), ("other_lines", other_lines), ("code_lines", code_lines),
        ("needed", needed),
        ("thin", bool(test_files) and test_lines * 4 < other_lines),
    ])


def score_risk(files, tests_info, conflicts):
    reasons = []
    real = [f for f in files if not f["generated"]]

    sens = [f for f in real if set(f["risky_kinds"]) & {"security", "payments"}]
    if sens:
        n = lines(sens)
        new_flow = [f for f in sens if f["change"] == "added" and "security" in f["risky_kinds"]
                    and f["additions"] >= 30]
        if n >= 200 or new_flow:
            pts = 3
            what = ("New login, token, or permission code" if new_flow and n < 200
                    else "Large change to sensitive code")
        elif n >= 50:
            pts, what = 2, "Changes sensitive code"
        else:
            pts, what = 1, "Small change to sensitive code"
        reasons.append(OrderedDict([("points", pts), ("rule", "sensitive"),
                                    ("reason", "%s (%d lines): %s" % (what, n, sample([f["path"] for f in sens])))]))

    mig = [f for f in real if "migration" in f["risky_kinds"]]
    if mig:
        changing = [f for f in mig if f.get("migration_changes") or f["change"] == "deleted"]
        if changing:
            reasons.append(OrderedDict([("points", 2), ("rule", "migration"),
                                        ("reason", "Migration changes or drops existing data: "
                                         + sample([f["path"] for f in changing]))]))
        else:
            reasons.append(OrderedDict([("points", 1), ("rule", "migration"),
                                        ("reason", "Migration only adds: " + sample([f["path"] for f in mig]))]))

    cfg = [f["path"] for f in real if set(f["risky_kinds"]) & {"config", "ci"}]
    if cfg:
        reasons.append(OrderedDict([("points", 1), ("rule", "config_ci"),
                                    ("reason", "Changes config or CI: " + sample(cfg))]))
    deps = [f["path"] for f in real if f["deps"]]
    if deps:
        reasons.append(OrderedDict([("points", 1), ("rule", "deps"),
                                    ("reason", "Changes dependency manifests: " + sample(deps))]))

    size = lines(real)
    for limit, pts in ((3000, 3), (1000, 2), (300, 1)):
        if size >= limit:
            reasons.append(OrderedDict([("points", pts), ("rule", "size"),
                                        ("reason", "Large change: %d real lines" % size)]))
            break

    if tests_info["needed"]:
        if not tests_info["present"]:
            reasons.append(OrderedDict([("points", 2), ("rule", "no_tests"),
                                        ("reason", "No tests changed for %d code lines" % tests_info["code_lines"])]))
        elif tests_info["thin"]:
            reasons.append(OrderedDict([("points", 1), ("rule", "thin_tests"),
                                        ("reason", "Tests look thin: %d test lines next to %d other lines"
                                         % (tests_info["lines"], tests_info["other_lines"]))]))
        elif sens or mig:
            reasons.append(OrderedDict([("points", -1), ("rule", "tests_cover"),
                                        ("reason", "Tests changed alongside the risky code (%d test lines)"
                                         % tests_info["lines"])]))

    if conflicts["checked"]:
        real_overlaps = [o for o in conflicts["overlaps"] if not o["generated_only"]]
        hard = [o for o in real_overlaps if o["kind"] == "conflict"]
        if conflicts["base_conflict"] or hard:
            bits = []
            if conflicts["base_conflict"]:
                bits.append("conflicts with " + (conflicts["base"] or "the base branch"))
            if hard:
                bits.append("conflicts with open " + ", ".join("PR %d" % o["number"] for o in hard[:3]))
            reasons.append(OrderedDict([("points", 2), ("rule", "conflicts"),
                                        ("reason", "Real conflict: " + "; ".join(bits))]))
        elif real_overlaps:
            clean = all(o["kind"] == "overlap" for o in real_overlaps)
            word = "Overlaps (merges cleanly)" if clean else "Overlaps (file overlap only)"
            reasons.append(OrderedDict([("points", 1), ("rule", "overlap"),
                                        ("reason", "%s with open %s" % (word, ", ".join(
                                            "PR %d" % o["number"] for o in real_overlaps[:3])))]))

    raw = 1 + sum(r["points"] for r in reasons)
    floor = 2 if (sens or mig) else 1
    score = max(floor, min(10, raw))
    level = "low" if score <= 3 else ("medium" if score <= 6 else "high")
    reasons.sort(key=lambda r: -r["points"])
    if not reasons:
        reasons.append(OrderedDict([("points", 0), ("rule", "none"),
                                    ("reason", "Small change with no risky areas")]))
    return OrderedDict([("score", score), ("raw_score", raw), ("max", 10),
                        ("level", level), ("percent", score * 10), ("reasons", reasons)])


# --------------------------------------------------------------------------
# git helpers and the real conflict check (SKILL.md step 4)
# --------------------------------------------------------------------------

def git(args, check=False):
    proc = subprocess.run(["git"] + args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise Fail(5, "git_error", "git %s failed" % args[0], proc.stderr.strip()[:500])
    return proc.returncode, proc.stdout, proc.stderr.strip()


def git_version_ok():
    code, out, _ = git(["version"])
    m = re.search(r"(\d+)\.(\d+)", out)
    return code == 0 and m and (int(m.group(1)), int(m.group(2))) >= (2, 38)


def remote_for(repo):
    """Name of the git remote that points at OWNER/REPO, or None."""
    code, out, _ = git(["remote", "-v"])
    if code != 0:
        return None
    want = repo.lower()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        url = parts[1].lower().rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        if url.endswith("/" + want) or url.endswith(":" + want):
            return parts[0]
    return None


def real_check_blocker(repo):
    """Why the real check cannot run here, or None if it can."""
    if git(["rev-parse", "--is-inside-work-tree"])[0] != 0:
        return "not run in a local clone of %s" % repo, None
    remote = remote_for(repo)
    if not remote:
        return "not run in a local clone of %s" % repo, None
    if not git_version_ok():
        return "git is older than 2.38", None
    if git(["rev-parse", "--is-shallow-repository"])[1].strip() == "true":
        return "shallow clone", None
    return None, remote


def merge_check(a, b):
    """('clean'|'conflict'|'error', conflicted files) for merging a and b."""
    code, out, _ = git(["merge-tree", "--write-tree", "--name-only", "--no-messages", a, b])
    rows = out.splitlines()
    if code == 0:
        return "clean", []
    if code == 1 and rows and re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", rows[0].strip()):
        return "conflict", sorted({r for r in rows[1:] if r.strip()})
    return "error", []


def drop_prism_refs():
    _, out, _ = git(["for-each-ref", "--format=%(refname)", "refs/prism/"])
    for ref in out.split():
        git(["update-ref", "-d", ref])


def new_conflicts(state, base, mergeable):
    return OrderedDict([
        ("checked", False), ("state", state), ("base", base), ("mergeable", mergeable),
        ("method", None), ("fallback_reason", None),
        ("base_conflict", False), ("base_conflict_files", []),
        ("conflicting_with_base", False), ("overlaps", []),
        ("open_prs_checked", False), ("error", None),
    ])


def find_overlaps(conflicts, env, repo, base, mine, gen_paths, skip_number=None):
    """Fill conflicts['overlaps'] with open PRs on `base` that share files with `mine`."""
    code, out, err = gh(["pr", "list", "--repo", repo, "--base", base, "--state", "open",
                         "--limit", "100", "--json", "number,title,headRefName,url,files,mergeable"], env)
    if code != 0:
        conflicts["error"] = "Could not list open PRs: " + err[:300]
        return
    conflicts["open_prs_checked"] = True
    for other in json.loads(out or "[]"):
        if other.get("number") == skip_number:
            continue
        theirs = {x["path"] for x in (other.get("files") or [])}
        shared = sorted(mine & theirs)
        if shared:
            conflicts["overlaps"].append(OrderedDict([
                ("number", other["number"]), ("title", other.get("title")),
                ("head", other.get("headRefName")), ("url", other.get("url")),
                ("files", shared),
                ("generated_only", all(p in gen_paths for p in shared)),
                ("kind", "potential"), ("conflict_files", []),
                ("other_out_of_date", other.get("mergeable") == "CONFLICTING"),
            ]))
    conflicts["overlaps"].sort(key=lambda o: (o["generated_only"], -len(o["files"])))


def run_real_check(conflicts, repo, base_ref, head_ref, fetch_specs, base_label):
    """merge-tree the head against the base and each sharing PR.

    fetch_specs: refspecs to fetch into refs/prism/ (may be empty in branch mode).
    base_ref / head_ref: refs to compare (refs/prism/... or local refs).
    """
    blocker, remote = real_check_blocker(repo)
    if blocker:
        conflicts["method"], conflicts["fallback_reason"] = "file-overlap", blocker
        return False
    try:
        if fetch_specs:
            code, _, err = git(["fetch", "--no-tags", "--quiet", "--no-write-fetch-head", remote] + fetch_specs)
            if code != 0:
                conflicts["method"], conflicts["fallback_reason"] = "file-overlap", "git fetch failed"
                return False
        if base_ref:
            res, files = merge_check(base_ref, head_ref)
            if res == "error":
                conflicts["method"], conflicts["fallback_reason"] = "file-overlap", "git merge-tree failed against " + base_label
                return False
            conflicts["base_conflict"] = res == "conflict"
            conflicts["base_conflict_files"] = files
        for o in conflicts["overlaps"]:
            if o["generated_only"]:
                o["kind"] = "overlap"
                continue
            res, files = merge_check(head_ref, "refs/prism/pr-%d" % o["number"])
            if res == "error":
                o["kind"] = "potential"
                continue
            shared = [f for f in files if f in set(o["files"])]
            o["kind"] = "conflict" if shared else "overlap"
            o["conflict_files"] = shared
        conflicts["method"] = "merge-tree"
        return True
    finally:
        drop_prism_refs()


# --------------------------------------------------------------------------
# Shared analysis for every mode
# --------------------------------------------------------------------------

CHANGE_MAP = {"added": "added", "removed": "deleted", "modified": "modified",
              "renamed": "renamed", "copied": "added", "changed": "modified",
              "unchanged": "modified"}


def file_from_api(r):
    f = OrderedDict([("path", r["filename"]),
                     ("change", CHANGE_MAP.get(r.get("status"), "modified")),
                     ("additions", r.get("additions") or 0),
                     ("deletions", r.get("deletions") or 0)])
    if r.get("previous_filename"):
        f["previous_path"] = r["previous_filename"]
    classify(f)
    if "migration" in f["risky_kinds"]:
        f["migration_changes"] = bool(MIGRATION_CHANGE_RE.search(r.get("patch") or ""))
    return f


def tot(fs):
    return OrderedDict([("files", len(fs)), ("additions", sum(f["additions"] for f in fs)),
                        ("deletions", sum(f["deletions"] for f in fs))])


def diff_url(pr_url, path):
    return "%s/files#diff-%s" % (pr_url.rstrip("/"), hashlib.sha256(path.encode("utf-8")).hexdigest())


def analyze(files, conflicts, max_nodes, pr_url):
    real_files = [f for f in files if not f["generated"]]
    totals = OrderedDict([("real", tot(real_files)), ("all", tot(files)),
                          ("generated", tot([f for f in files if f["generated"]]))])
    tests_info = tests_summary(files)
    modules = build_modules(files, max_nodes)
    files_json = OrderedDict()
    for m in modules:
        entries = []
        for f in files:
            if f.get("module") != m["id"]:
                continue
            e = OrderedDict([("path", f["path"])])
            if pr_url:
                e["url"] = diff_url(pr_url, f["path"])
            e.update([("add", f["additions"]), ("del", f["deletions"]),
                      ("status", f["status"]), ("generated", f["generated"])])
            entries.append(e)
        files_json[m["id"]] = OrderedDict([("label", m["label"]), ("files", entries)])

    big = lines(real_files) >= 2000 or len(real_files) >= 40
    ranked = sorted([f for f in real_files if not f["tests"] and not f["doc"]],
                    key=lambda f: (not f["risky"], -(f["additions"] + f["deletions"])))
    risky = [f for f in files if f["risky"]]
    read_plan = OrderedDict([
        ("big", big),
        ("important_files", [f["path"] for f in ranked[:15]]),
        ("risky_files", [OrderedDict([("path", f["path"]), ("kinds", f["risky_kinds"])])
                         for f in risky[:30]]),
        ("risky_files_total", len(risky)),
    ])
    risk = score_risk(files, tests_info, conflicts)
    for f in files:
        f.pop("doc", None)
    return OrderedDict([("totals", totals), ("tests", tests_info), ("conflicts", conflicts),
                        ("risk", risk), ("modules", modules), ("read_plan", read_plan),
                        ("files", files), ("files_json", files_json)])


# --------------------------------------------------------------------------
# PR mode (and since mode)
# --------------------------------------------------------------------------

def gh_setup(host):
    if not shutil.which("gh"):
        raise Fail(2, "gh_missing", "GitHub CLI (gh) is not installed. Install it from https://cli.github.com/")
    env = dict(os.environ)
    if host and host != "github.com":
        env["GH_HOST"] = host
    check_host = host or env.get("GH_HOST") or "github.com"
    code, _, err = gh(["auth", "status", "--hostname", check_host], env)
    if code != 0:
        raise Fail(3, "gh_not_logged_in",
                   "gh is not logged in to %s. Run: gh auth login" % check_host, err)
    return env


def pr_files(env, repo, number):
    jq = (".[] | {filename,status,additions,deletions,previous_filename,"
          "patch: (if (.filename | test(\"%s\")) then .patch else null end)}" % MIGRATION_PATCH_RE)
    code, out, err = gh(["api", "--paginate", "repos/%s/pulls/%d/files?per_page=100" % (repo, number),
                         "--jq", jq], env)
    if code != 0:
        raise Fail(5, "gh_error", "gh failed while listing PR files", err)
    return [file_from_api(json.loads(line)) for line in out.splitlines() if line.strip()]


def resolve_since(env, repo, number, head_oid, since):
    """Return (since_info, delta_files or None). None means use the full PR."""
    info = OrderedDict([("requested", since), ("from", None), ("from_short", None),
                        ("reviewed_at", None), ("status", None), ("total_commits", None),
                        ("commits", []), ("has_merge_commits", False),
                        ("files_capped", False), ("fallback_reason", None), ("nothing_new", False)])
    start = since
    if since == "last":
        code, login, err = gh(["api", "user", "--jq", ".login"], env)
        if code != 0:
            raise Fail(5, "gh_error", "Could not read your GitHub login", err)
        jq = ('.[] | select(.user.login == "%s" and .state != "PENDING") '
              '| "\\(.commit_id) \\(.submitted_at)"' % login.strip())
        code, out, err = gh(["api", "--paginate", "repos/%s/pulls/%d/reviews" % (repo, number), "--jq", jq], env)
        if code != 0:
            raise Fail(5, "gh_error", "Could not list reviews", err)
        rows = [r for r in out.splitlines() if r.strip()]
        if not rows:
            info["fallback_reason"] = "You have not reviewed this PR yet, so this shows the full PR."
            return info, None
        start, info["reviewed_at"] = rows[-1].split()[0], rows[-1].split()[1]
    info["from"], info["from_short"] = start, start[:7]
    jq = ('{status, total_commits, commits: [.commits[] | {sha: .sha[0:7], parents: (.parents | length), '
          'msg: (.commit.message | split("\\n")[0])}], files: [.files[] | {filename, status, additions, '
          'deletions, previous_filename, patch: (if (.filename | test("%s")) then .patch else null end)}]}'
          % MIGRATION_PATCH_RE)
    code, out, err = gh(["api", "repos/%s/compare/%s...%s" % (repo, start, head_oid), "--jq", jq], env)
    if code != 0:
        info["status"] = "missing"
        info["fallback_reason"] = ("Commit %s is no longer in this branch (likely a force-push or rebase), "
                                   "so this shows the full PR." % start[:7])
        return info, None
    data = json.loads(out)
    info["status"], info["total_commits"] = data.get("status"), data.get("total_commits")
    info["commits"] = [OrderedDict([("sha", c["sha"]), ("msg", c["msg"])]) for c in data.get("commits") or []][:50]
    info["has_merge_commits"] = any(c.get("parents", 1) > 1 for c in data.get("commits") or [])
    if info["status"] == "identical":
        info["nothing_new"] = True
        return info, []
    if info["status"] != "ahead":
        info["fallback_reason"] = ("Commit %s is no longer in this branch (likely a force-push or rebase), "
                                   "so this shows the full PR." % start[:7])
        return info, None
    files = [file_from_api(r) for r in data.get("files") or []]
    info["files_capped"] = len(files) >= 300
    return info, files


def collect_pr(target, repo_flag, max_nodes, check_overlaps=True, since=None, real_check=True):
    host, repo, number = parse_target(target, repo_flag)
    env = gh_setup(host)
    repo_args = ["--repo", repo] if repo else []
    fields = ("number,title,body,author,state,isDraft,baseRefName,headRefName,headRefOid,"
              "additions,deletions,changedFiles,mergeable,mergedAt,url,commits")
    pr = gh_json(["pr", "view", str(number), "--json", fields] + repo_args, env, "PR %d" % number)
    if pr.get("mergeable") == "UNKNOWN" and pr.get("state") == "OPEN":
        time.sleep(2)  # GitHub computes mergeability lazily; ask once more.
        again = gh_json(["pr", "view", str(number), "--json", "mergeable"] + repo_args, env, "PR %d" % number)
        pr["mergeable"] = again.get("mergeable", pr["mergeable"])
    if not repo:
        m = re.match(r"https?://[^/]+/([^/]+/[^/]+)/pull/", pr.get("url", ""))
        repo = m.group(1) if m else None
    if not repo:
        raise Fail(5, "no_repo", "Could not work out the repo from the PR URL.")

    full = pr_files(env, repo, number)
    state = (pr.get("state") or "").lower()
    base = pr.get("baseRefName")

    since_info, files = None, full
    if since:
        since_info, delta = resolve_since(env, repo, number, pr.get("headRefOid"), since)
        if delta is not None:
            files = delta

    conflicts = new_conflicts(state, base, pr.get("mergeable"))
    if state == "open":
        conflicts["checked"] = True
        mine = {f["path"] for f in full} | {f["previous_path"] for f in full if "previous_path" in f}
        gen_paths = {f["path"] for f in full if f["generated"]}
        if check_overlaps:
            find_overlaps(conflicts, env, repo, base, mine, gen_paths, skip_number=number)
        ran = False
        if real_check:
            specs = ["+refs/heads/%s:refs/prism/base" % base,
                     "+refs/pull/%d/head:refs/prism/pr-%d" % (number, number)]
            specs += ["+refs/pull/%d/head:refs/prism/pr-%d" % (o["number"], o["number"])
                      for o in conflicts["overlaps"] if not o["generated_only"]]
            ran = run_real_check(conflicts, repo, "refs/prism/base", "refs/prism/pr-%d" % number,
                                 specs, base)
        else:
            conflicts["method"], conflicts["fallback_reason"] = "file-overlap", "real check turned off"
        if not ran:
            conflicts["base_conflict"] = pr.get("mergeable") == "CONFLICTING"
        conflicts["conflicting_with_base"] = conflicts["base_conflict"]

    result = analyze(files, conflicts, max_nodes, pr.get("url"))
    if since_info is not None:
        full_real = [f for f in full if not f["generated"]]
        result["totals"]["full_pr"] = tot(full)
        result["totals"]["full_pr_real"] = tot(full_real)
    result["totals"]["github"] = OrderedDict([("files", pr.get("changedFiles")),
                                              ("additions", pr.get("additions")),
                                              ("deletions", pr.get("deletions"))])
    all_full = tot(full)
    result["totals"]["matches_github"] = (all_full["additions"] == pr.get("additions")
                                          and all_full["deletions"] == pr.get("deletions")
                                          and all_full["files"] == pr.get("changedFiles"))
    result["totals"]["files_truncated"] = len(full) < (pr.get("changedFiles") or 0)

    author = pr.get("author") or {}
    commits = pr.get("commits") or []
    body = pr.get("body") or ""
    meta = OrderedDict([
        ("mode", "since" if since_info and since_info["fallback_reason"] is None else "pr"),
        ("repo", repo), ("number", pr.get("number")), ("title", pr.get("title")),
        ("url", pr.get("url")), ("author", author.get("login")),
        ("state", state), ("draft", pr.get("isDraft", False)),
        ("base", base), ("head", pr.get("headRefName")), ("head_oid", pr.get("headRefOid")),
        ("mergeable", pr.get("mergeable")), ("merged_at", pr.get("mergedAt")),
        ("body", body[:4000] + ("..." if len(body) > 4000 else "")),
        ("commit_count", len(commits)),
        ("commits", [c.get("messageHeadline") for c in commits[:50]]),
    ])
    out = OrderedDict([("ok", True), ("pr", meta)])
    if since_info is not None:
        out["since"] = since_info
    out.update(result)
    return out


# --------------------------------------------------------------------------
# Branch mode (author mode: no PR yet)
# --------------------------------------------------------------------------

def detect_base(base_flag):
    if base_flag:
        name = base_flag
    else:
        code, out, _ = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
        if code == 0 and out.strip():
            name = out.strip().split("/", 1)[-1]
        elif git(["rev-parse", "--verify", "--quiet", "main"])[0] == 0:
            name = "main"
        elif git(["rev-parse", "--verify", "--quiet", "master"])[0] == 0:
            name = "master"
        else:
            raise Fail(4, "no_base", "Could not find the base branch. Pass --base NAME.")
    if git(["rev-parse", "--verify", "--quiet", "origin/" + name])[0] == 0:
        return name, "origin/" + name
    if git(["rev-parse", "--verify", "--quiet", name])[0] == 0:
        return name, name
    raise Fail(4, "no_base", "Base branch %s does not exist here." % name)


def parse_z_pairs(out, numstat):
    """Parse `git diff -z --numstat` or `--name-status` output into {path: info}."""
    toks = out.split("\0")
    res = OrderedDict()
    i = 0
    while i < len(toks):
        t = toks[i]
        if not t:
            i += 1
            continue
        if numstat:
            adds, dels, path = t.split("\t", 2)
            prev = None
            if path == "":  # rename: path empty, then old and new
                prev, path = toks[i + 1], toks[i + 2]
                i += 3
            else:
                i += 1
            res[path] = (0 if adds == "-" else int(adds), 0 if dels == "-" else int(dels), prev)
        else:
            status = t
            if status[0] in "RC":
                prev, path = toks[i + 1], toks[i + 2]
                i += 3
            else:
                prev, path = None, toks[i + 1]
                i += 2
            res[path] = (status[0], prev)
    return res


def count_lines(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return 0
    if b"\0" in data[:8000]:
        return 0
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def collect_branch(base_flag, include_uncommitted, max_nodes, check_overlaps=True, real_check=True):
    if git(["rev-parse", "--is-inside-work-tree"])[0] != 0:
        raise Fail(4, "not_git", "Not in a git repo. Give a PR number or link instead.")
    branch = git(["branch", "--show-current"])[1].strip()
    if not branch:
        raise Fail(4, "detached", "Detached HEAD. Check out a branch or give a PR.")
    base, base_ref = detect_base(base_flag)
    if branch == base:
        raise Fail(4, "on_base", "You are on the base branch %s; there is nothing to compare." % base)

    rng = ["--merge-base", base_ref] if include_uncommitted else ["%s...HEAD" % base_ref]
    numstat = parse_z_pairs(git(["diff", "-z", "-M", "--numstat"] + rng, check=True)[1], True)
    names = parse_z_pairs(git(["diff", "-z", "-M", "--name-status"] + rng, check=True)[1], False)
    letter = {"A": "added", "D": "deleted", "R": "renamed", "C": "added"}
    files = []
    for path, (adds, dels, prev) in numstat.items():
        st, prev2 = names.get(path, ("M", None))
        f = OrderedDict([("path", path), ("change", letter.get(st, "modified")),
                         ("additions", adds), ("deletions", dels)])
        if prev or prev2:
            f["previous_path"] = prev or prev2
        classify(f)
        if "migration" in f["risky_kinds"]:
            patch = git(["diff"] + rng + ["--", path])[1]
            f["migration_changes"] = bool(MIGRATION_CHANGE_RE.search(patch))
        files.append(f)
    if include_uncommitted:
        top = git(["rev-parse", "--show-toplevel"])[1].strip()
        for path in git(["ls-files", "--others", "--exclude-standard", "-z"])[1].split("\0"):
            if path and path not in numstat:
                f = OrderedDict([("path", path), ("change", "added"),
                                 ("additions", count_lines(os.path.join(top, path))), ("deletions", 0)])
                classify(f)
                files.append(f)
    uncommitted = len([l for l in git(["status", "--porcelain"])[1].splitlines() if l.strip()])
    ahead = int(git(["rev-list", "--count", "%s..HEAD" % base_ref])[1].strip() or 0)
    if not files:
        raise Fail(4, "nothing_to_compare", "No changes between %s and %s yet." % (base_ref, branch))

    gh_ok = bool(shutil.which("gh")) and gh(["auth", "status"])[0] == 0
    env = dict(os.environ)
    repo = None
    if gh_ok:
        code, out, _ = gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], env)
        repo = out.strip() if code == 0 and out.strip() else None
    label = repo or os.path.basename(git(["rev-parse", "--show-toplevel"])[1].strip())

    conflicts = new_conflicts("open", base, None)
    conflicts["checked"] = True
    res, cfiles = merge_check(base_ref, "HEAD") if git_version_ok() else ("error", [])
    if res != "error":
        conflicts["base_conflict"] = res == "conflict"
        conflicts["base_conflict_files"] = cfiles
        conflicts["method"] = "merge-tree"
    else:
        conflicts["method"], conflicts["fallback_reason"] = "file-overlap", "git is older than 2.38"
    if check_overlaps and gh_ok and repo:
        mine = {f["path"] for f in files} | {f["previous_path"] for f in files if "previous_path" in f}
        gen_paths = {f["path"] for f in files if f["generated"]}
        find_overlaps(conflicts, env, repo, base, mine, gen_paths)
        sharing = [o for o in conflicts["overlaps"] if not o["generated_only"]]
        if sharing and real_check and conflicts["method"] == "merge-tree":
            specs = ["+refs/pull/%d/head:refs/prism/pr-%d" % (o["number"], o["number"]) for o in sharing]
            if not run_real_check(conflicts, repo, None, "HEAD", specs, base):
                conflicts["method"] = "merge-tree"  # the base check still ran
                conflicts["fallback_reason"] = ("open PRs: file overlap only, "
                                                + (conflicts["fallback_reason"] or "check failed"))
    elif check_overlaps:
        conflicts["error"] = ("Open PR check skipped: gh is not available or not logged in." if not gh_ok
                              else "Open PR check skipped: this repo has no GitHub remote.")
    conflicts["conflicting_with_base"] = conflicts["base_conflict"]

    result = analyze(files, conflicts, max_nodes, None)
    log = git(["log", "--format=%h %s", "%s..HEAD" % base_ref])[1].splitlines()
    meta = OrderedDict([
        ("mode", "branch"), ("repo", label), ("number", None), ("title", None), ("url", None),
        ("author", git(["config", "user.name"])[1].strip() or None),
        ("state", "draft"), ("draft", True), ("base", base), ("base_ref", base_ref),
        ("head", branch), ("safe_name", re.sub(r"[^A-Za-z0-9._-]", "-", branch)),
        ("commit_count", ahead), ("commits", log[:50]),
        ("uncommitted_files", uncommitted), ("includes_uncommitted", include_uncommitted),
        ("pushed", git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])[0] == 0),
    ])
    out = OrderedDict([("ok", True), ("pr", meta)])
    out.update(result)
    return out


# --------------------------------------------------------------------------
# Output helpers and CLI
# --------------------------------------------------------------------------

def brief(result, keep=10):
    """Short view: no per-file lists, at most `keep` paths per module or overlap."""
    out = json.loads(json.dumps(result), object_pairs_hook=OrderedDict)
    out.pop("files", None)
    out.pop("files_json", None)
    for item in out.get("modules", []) + out.get("conflicts", {}).get("overlaps", []):
        extra = len(item["files"]) - keep
        if extra > 0:
            item["files"] = item["files"][:keep]
            item["files_more"] = extra
    return out


def fill_files(page, saved):
    """Replace {{FILES_JSON}} in an HTML page with files_json from a saved run."""
    try:
        with open(saved, encoding="utf-8") as fh:
            data = json.load(fh)
        with open(page, encoding="utf-8") as fh:
            html = fh.read()
    except (OSError, ValueError) as e:
        raise Fail(4, "bad_input", "Could not read the page or saved JSON: %s" % e)
    if "files_json" not in data:
        raise Fail(4, "bad_input", "Saved JSON has no files_json. Re-run the collector with --save.")
    if "{{FILES_JSON}}" not in html:
        raise Fail(4, "bad_input", "No {{FILES_JSON}} placeholder left in " + page)
    # Keep "</script>" in a path from closing the JSON script tag early.
    blob = json.dumps(data["files_json"], ensure_ascii=False).replace("</", "<\\/")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(html.replace("{{FILES_JSON}}", blob))
    return OrderedDict([("ok", True), ("filled", page), ("nodes", len(data["files_json"]))])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect PR facts for PRism as JSON.")
    ap.add_argument("pr", nargs="?", help="PR number, OWNER/REPO#N, or PR URL")
    ap.add_argument("--repo", help="OWNER/REPO (or HOST/OWNER/REPO); overrides the URL repo")
    ap.add_argument("--since", metavar="SHA|last",
                    help="only the changes since a commit, or since your last review ('last')")
    ap.add_argument("--branch", action="store_true",
                    help="author mode: the current branch compared with its base, no PR needed")
    ap.add_argument("--base", help="author mode: base branch name (default: origin/HEAD, main, master)")
    ap.add_argument("--uncommitted", action="store_true",
                    help="author mode: include staged, unstaged, and untracked changes")
    ap.add_argument("--max-nodes", type=int, default=10,
                    help="map node budget including HEAD and BASE (default 10)")
    ap.add_argument("--no-overlaps", action="store_true", help="skip the open-PR overlap check")
    ap.add_argument("--no-real-check", action="store_true",
                    help="skip git merge-tree; use file overlap only")
    ap.add_argument("--save", metavar="FILE",
                    help="write the full JSON to FILE and print it without the long "
                         "'files' and 'files_json' keys")
    ap.add_argument("--fill-files", nargs=2, metavar=("PAGE", "SAVED_JSON"),
                    help="replace {{FILES_JSON}} in PAGE with files_json from a --save file")
    args = ap.parse_args(argv)
    try:
        if args.fill_files:
            result = fill_files(*args.fill_files)
        else:
            nodes = max(4, args.max_nodes)
            if args.branch:
                result = collect_branch(args.base, args.uncommitted, nodes,
                                        not args.no_overlaps, not args.no_real_check)
            elif not args.pr:
                raise Fail(4, "bad_input", "Give a PR number or URL, or --branch.")
            else:
                result = collect_pr(args.pr, args.repo, nodes, not args.no_overlaps,
                                    args.since, not args.no_real_check)
            if args.save:
                try:
                    with open(args.save, "w", encoding="utf-8") as fh:
                        json.dump(result, fh, indent=1, ensure_ascii=False)
                except OSError as e:
                    raise Fail(4, "bad_input", "Could not write --save file: %s" % e)
                result = brief(result)
                result["saved"] = args.save
    except Fail as e:
        out = OrderedDict([("ok", False), ("error", e.error), ("message", e.message)])
        if e.detail:
            out["detail"] = e.detail
        print(json.dumps(out, indent=1, ensure_ascii=False))
        print("prism_collect: " + e.message, file=sys.stderr)
        return e.code
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
