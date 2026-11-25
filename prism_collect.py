#!/usr/bin/env python3
"""PRism collector: gather the mechanical facts about a GitHub PR as JSON.

Usage:
    python3 prism_collect.py <PR number or URL> [--repo OWNER/REPO] [--max-nodes 10]
                             [--no-overlaps] [--save FILE]
    python3 prism_collect.py --fill-files PAGE.html FILE

It shells out to the GitHub CLI (`gh`) and prints one JSON object to stdout:
PR metadata, every changed file with its flags, map modules, totals, tests,
overlaps with other open PRs, and the risk score with itemized reasons.
With --save FILE the full JSON goes to FILE and stdout skips the long
"files" and "files_json" keys. --fill-files puts files_json from a saved run
into a page's {{FILES_JSON}} placeholder.
The SKILL.md rubric is implemented here; this file is the source of truth.

Standard library only. It never reads tokens itself; `gh` handles auth.

Exit codes: 0 ok, 2 gh missing, 3 gh not logged in, 4 bad input or PR not
found, 5 other gh error. On error, stdout is {"ok": false, "error": ..., "message": ...}.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import OrderedDict

# --------------------------------------------------------------------------
# Classification rules (SKILL.md step 4 describes these in plain words)
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
# Risk
# --------------------------------------------------------------------------

def sample(paths, n=2):
    s = ", ".join(paths[:n])
    return s + (" (+%d more)" % (len(paths) - n) if len(paths) > n else "")


def score_risk(files, real, tests_info, conflicts):
    reasons = []
    real_files = [f for f in files if not f["generated"]]

    def touching(kind):
        return [f["path"] for f in real_files if kind in f["risky_kinds"]]

    sec = touching("security")
    if sec:
        reasons.append({"points": 3, "rule": "security",
                        "reason": "Touches auth, permissions, or security: " + sample(sec)})
    mig = touching("migration")
    if mig:
        reasons.append({"points": 2, "rule": "migration",
                        "reason": "Changes schema or migrations: " + sample(mig)})
    cfg = touching("config") + touching("ci")
    if cfg:
        reasons.append({"points": 1, "rule": "config_ci",
                        "reason": "Changes config or CI: " + sample(cfg)})
    deps = [f["path"] for f in real_files if f["deps"]]
    if deps:
        reasons.append({"points": 1, "rule": "deps",
                        "reason": "Changes dependency manifests: " + sample(deps)})
    adds = real["additions"]
    if adds >= 1500:
        reasons.append({"points": 2, "rule": "size",
                        "reason": "Large change: %d real lines added" % adds})
    elif adds >= 500:
        reasons.append({"points": 1, "rule": "size",
                        "reason": "Medium-large change: %d real lines added" % adds})
    if tests_info["needed"] and not tests_info["present"]:
        reasons.append({"points": 2, "rule": "no_tests",
                        "reason": "No tests changed for %d added code lines" % tests_info["code_additions"]})
    elif tests_info["thin"]:
        reasons.append({"points": 1, "rule": "thin_tests",
                        "reason": "Tests look thin: %d test lines for %d code lines"
                                  % (tests_info["additions"], tests_info["code_additions"])})
    if conflicts["checked"]:
        bits = []
        if conflicts["conflicting_with_base"]:
            bits.append("already conflicts with " + conflicts["base"])
        real_overlaps = [o for o in conflicts["overlaps"] if not o["generated_only"]]
        if real_overlaps:
            bits.append("overlaps open " + ", ".join("PR %d" % o["number"] for o in real_overlaps[:3])
                        + (" and %d more" % (len(real_overlaps) - 3) if len(real_overlaps) > 3 else ""))
        if bits:
            reasons.append({"points": 2, "rule": "conflicts",
                            "reason": "Conflicts: " + "; ".join(bits)})
    raw = 1 + sum(r["points"] for r in reasons)
    score = min(10, raw)
    level = "low" if score <= 3 else ("medium" if score <= 6 else "high")
    if not reasons:
        reasons.append({"points": 0, "rule": "none",
                        "reason": "Small change with no risky areas"})
    return OrderedDict([("score", score), ("raw_score", raw), ("max", 10),
                        ("level", level), ("percent", score * 10), ("reasons", reasons)])


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def collect(target, repo_flag, max_nodes, check_overlaps=True):
    if not shutil.which("gh"):
        raise Fail(2, "gh_missing", "GitHub CLI (gh) is not installed. Install it from https://cli.github.com/")

    host, repo, number = parse_target(target, repo_flag)
    env = dict(os.environ)
    if host and host != "github.com":
        env["GH_HOST"] = host
    check_host = host or env.get("GH_HOST") or "github.com"
    code, _, err = gh(["auth", "status", "--hostname", check_host], env)
    if code != 0:
        raise Fail(3, "gh_not_logged_in",
                   "gh is not logged in to %s. Run: gh auth login" % check_host, err)

    repo_args = ["--repo", repo] if repo else []
    fields = ("number,title,body,author,state,isDraft,baseRefName,headRefName,"
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

    # Files with change type, via the REST endpoint (paginated, up to 3000 files).
    code, out, err = gh(["api", "--paginate", "repos/%s/pulls/%d/files?per_page=100" % (repo, number),
                         "--jq", ".[] | {filename,status,additions,deletions,previous_filename}"], env)
    if code != 0:
        raise Fail(5, "gh_error", "gh failed while listing PR files", err)
    change_map = {"added": "added", "removed": "deleted", "modified": "modified",
                  "renamed": "renamed", "copied": "added", "changed": "modified",
                  "unchanged": "modified"}
    files = []
    for line in out.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        f = OrderedDict([("path", r["filename"]),
                         ("change", change_map.get(r.get("status"), "modified")),
                         ("additions", r.get("additions") or 0),
                         ("deletions", r.get("deletions") or 0)])
        if r.get("previous_filename"):
            f["previous_path"] = r["previous_filename"]
        files.append(classify(f))

    def tot(fs):
        return OrderedDict([("files", len(fs)), ("additions", sum(f["additions"] for f in fs)),
                            ("deletions", sum(f["deletions"] for f in fs))])

    real_files = [f for f in files if not f["generated"]]
    totals = OrderedDict([("real", tot(real_files)), ("all", tot(files)),
                          ("generated", tot([f for f in files if f["generated"]]))])
    totals["github"] = OrderedDict([("files", pr.get("changedFiles")),
                                    ("additions", pr.get("additions")),
                                    ("deletions", pr.get("deletions"))])
    totals["matches_github"] = (totals["all"]["additions"] == pr.get("additions")
                                and totals["all"]["deletions"] == pr.get("deletions")
                                and totals["all"]["files"] == pr.get("changedFiles"))
    totals["files_truncated"] = len(files) < (pr.get("changedFiles") or 0)

    test_files = [f for f in files if f["tests"]]
    code_adds = sum(f["additions"] for f in files if f["code"])
    test_adds = sum(f["additions"] for f in test_files)
    tests_info = OrderedDict([
        ("present", bool(test_files)), ("files", len(test_files)),
        ("additions", test_adds), ("code_additions", code_adds),
        ("needed", code_adds > 0),
        ("thin", bool(test_files) and code_adds >= 100 and test_adds * 5 < code_adds),
    ])

    state = (pr.get("state") or "").lower()
    conflicts = OrderedDict([("checked", False), ("state", state), ("base", pr.get("baseRefName")),
                             ("mergeable", pr.get("mergeable")),
                             ("conflicting_with_base", False), ("overlaps", []), ("error", None)])
    if state == "open":
        conflicts["checked"] = True
        conflicts["conflicting_with_base"] = pr.get("mergeable") == "CONFLICTING"
        if check_overlaps:
            mine = {f["path"] for f in files} | {f["previous_path"] for f in files if "previous_path" in f}
            gen_paths = {f["path"] for f in files if f["generated"]}
            code, out, err = gh(["pr", "list", "--repo", repo, "--base", pr["baseRefName"], "--state", "open",
                                 "--limit", "100", "--json", "number,title,headRefName,url,files"], env)
            if code != 0:
                conflicts["error"] = "Could not list open PRs: " + err[:300]
            else:
                for other in json.loads(out or "[]"):
                    if other.get("number") == number:
                        continue
                    theirs = {x["path"] for x in (other.get("files") or [])}
                    shared = sorted(mine & theirs)
                    if shared:
                        conflicts["overlaps"].append(OrderedDict([
                            ("number", other["number"]), ("title", other.get("title")),
                            ("head", other.get("headRefName")), ("url", other.get("url")),
                            ("files", shared),
                            ("generated_only", all(p in gen_paths for p in shared)),
                        ]))
                conflicts["overlaps"].sort(key=lambda o: (o["generated_only"], -len(o["files"])))

    modules = build_modules(files, max_nodes)
    files_json = OrderedDict()
    for m in modules:
        files_json[m["id"]] = OrderedDict([("label", m["label"]), ("files", [
            OrderedDict([("path", f["path"]), ("add", f["additions"]), ("del", f["deletions"]),
                         ("status", f["status"]), ("generated", f["generated"])])
            for f in files if f.get("module") == m["id"]])])

    big = (totals["real"]["additions"] + totals["real"]["deletions"] >= 2000
           or totals["real"]["files"] >= 40)
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

    author = pr.get("author") or {}
    commits = pr.get("commits") or []
    body = pr.get("body") or ""
    meta = OrderedDict([
        ("repo", repo), ("number", pr.get("number")), ("title", pr.get("title")),
        ("url", pr.get("url")), ("author", author.get("login")),
        ("state", state), ("draft", pr.get("isDraft", False)),
        ("base", pr.get("baseRefName")), ("head", pr.get("headRefName")),
        ("mergeable", pr.get("mergeable")), ("merged_at", pr.get("mergedAt")),
        ("body", body[:4000] + ("..." if len(body) > 4000 else "")),
        ("commit_count", len(commits)),
        ("commits", [c.get("messageHeadline") for c in commits[:50]]),
    ])

    for f in files:
        f.pop("doc", None)
    return OrderedDict([
        ("ok", True), ("pr", meta), ("totals", totals), ("tests", tests_info),
        ("conflicts", conflicts),
        ("risk", score_risk(files, totals["real"], tests_info, conflicts)),
        ("modules", modules), ("read_plan", read_plan), ("files", files),
        ("files_json", files_json),
    ])


def brief(result, keep=10):
    """Short view: no per-file lists, at most `keep` paths per module or overlap."""
    out = json.loads(json.dumps(result), object_pairs_hook=OrderedDict)
    out.pop("files", None)
    out.pop("files_json", None)
    for item in out["modules"] + out["conflicts"]["overlaps"]:
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
    ap.add_argument("--max-nodes", type=int, default=10,
                    help="map node budget including HEAD and BASE (default 10)")
    ap.add_argument("--no-overlaps", action="store_true", help="skip the open-PR overlap check")
    ap.add_argument("--save", metavar="FILE",
                    help="write the full JSON to FILE and print it without the long "
                         "'files' and 'files_json' keys")
    ap.add_argument("--fill-files", nargs=2, metavar=("PAGE", "SAVED_JSON"),
                    help="replace {{FILES_JSON}} in PAGE with files_json from a --save file")
    args = ap.parse_args(argv)
    try:
        if args.fill_files:
            result = fill_files(*args.fill_files)
        elif not args.pr:
            raise Fail(4, "bad_input", "Give a PR number or URL.")
        else:
            result = collect(args.pr, args.repo, max(4, args.max_nodes), not args.no_overlaps)
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
