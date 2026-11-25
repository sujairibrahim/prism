---
name: prism
description: Use when the user runs /prism <PR number or URL>, or asks to explain, visualize, or map a GitHub pull request by number or link.
argument-hint: <PR number or URL> [save]
---

# PRism 🔺

Show a clear flowchart of a GitHub pull request. Follow these steps in order. Do not skip steps. Use plain language in the HTML and in your short chat reply.

## 1. Parse the PR

Input: $ARGUMENTS (for example `/prism 23` or `/prism https://github.com/OWNER/REPO/pull/23`). If it is empty, use the PR number or link the user wrote in chat; if there is none, ask for it.

- If the user gave a number, use that number in the current repo.
- If the user gave a URL like `https://github.com/OWNER/REPO/pull/123`, use repo `OWNER/REPO` and number `123`. Pass `--repo OWNER/REPO` to every `gh` command.
- First run `gh auth status`. If it fails, stop and tell the user to run `gh auth login`.

## 2. Fetch PR data

Run:

```bash
gh pr view <N> --json number,title,body,author,state,baseRefName,headRefName,files,commits,additions,deletions,mergeable,mergedAt,url
gh pr diff <N>
```

Skim the diff so you can say what each module does. If the diff is huge (about 2000+ lines or 40+ files), use `gh pr diff <N> --name-only`, then read only the important files: risky files first, then the largest modules.

## 3. Conflict check

- If the PR is **open**:
  1. Run `gh pr list --base <baseRefName> --state open --json number,title,headRefName,files`.
  2. Find other open PRs that touch the same files. Those are potential conflicts.
  3. Also check `mergeable`. If it is `CONFLICTING`, say this PR already conflicts with the base branch.
- If the PR is **merged** or **closed**: say conflicts are already resolved or no longer apply, and skip the overlap check.

## 4. Group files, mute noise, classify

Split files into **real code** and **generated**.

**Generated** (mute these): lockfiles, `*.lock`, `*.snap`, migration snapshots, schema snapshots, and files under `dist/`, `build/`, `generated/`, `__generated__/`, `vendor/`, plus `*.min.*`. Put all of them in **one** node: `🤖 auto-generated N files +X/-Y`. Do not put this node on the review path. Do not include its lines in the "real code" headline. Still show a "total +A/-B" chip that counts every file.

**Overview map:** group the remaining real files by top-level folder or module. Keep the whole map to about **10-12 nodes** (branches and the generated node count toward this). Merge small leftover groups into `other N files`. The overview shows modules only, not individual files. Files belong in `{{FILES_JSON}}`, so a click can reveal them.

**Classify** each real module:
- 🟢 added · 🟡 modified · 🔴 deleted
- 🧪 tests — test files or folders
- 📦 dependencies — manifests like `package.json` or `requirements.txt` (lockfiles are generated, not this)
- 🔥 risky — auth, security, migrations, config, CI, permissions, payments
- Risky wins over added or modified. Tests stay 🧪.

## 5. Risk, review path, and diagram

**Risk meter 🔥** — start at 1, add the points below, cap at 10. Level: 1-3 low, 4-6 medium, 7-10 high.

- Auth, permissions, or security: +3
- Real schema or migration changes (not only a generated snapshot): +2
- Config or CI: +1
- Dependency manifest changes: +1
- Real code size: +1 if real additions are 500-1499, +2 if 1500 or more
- Tests: +2 if the change has no tests, +1 if tests look thin next to the real code
- Conflicts: +2 if `mergeable` is `CONFLICTING` or another open PR overlaps files

Give 2-4 short reasons that match the points you added.

**Review path 🧭** — pick the order a reviewer should read the modules, usually: data/schema → core logic → API → clients → tests/docs. Skip the generated node, branch nodes, and conflict nodes. Number the path modules ① ② ③ in their labels. Draw the path with thick arrows `==>` in that order, then color those arrows cyan with `linkStyle` (link index starts at 0, in the order links appear; the example below shows this). For each step, write one plain line that says why to look there.

**Diagram** — prefer `flowchart TB` so the review path reads top to bottom. Use a subgraph for the path, in order. Keep labels short: `① emoji module +adds/-dels`. Use fewer edges and fewer crossings. If you cannot infer flow, link `HEAD` to the first review node and to side nodes only. Dashed conflict links: `AUTH -.-> C38`. After every module node (including generated), add `click ID call showNode("ID")`.

**Colors** — always include these `classDef` rules:

```
classDef branch fill:#1e293b,stroke:#94a3b8,color:#e2e8f0
classDef added fill:#14532d,stroke:#22c55e,color:#dcfce7
classDef modified fill:#713f12,stroke:#eab308,color:#fef9c3
classDef deleted fill:#7f1d1d,stroke:#ef4444,color:#fee2e2
classDef tests fill:#1e3a8a,stroke:#3b82f6,color:#dbeafe
classDef deps fill:#581c87,stroke:#a855f7,color:#f3e8ff
classDef risky fill:#9a3412,stroke:#f97316,color:#ffedd5
classDef generated fill:#1f2937,stroke:#64748b,color:#94a3b8,stroke-dasharray:5 5
classDef conflict fill:#7f1d1d,stroke:#ef4444,color:#fecaca,stroke-dasharray:5 5
```

**Mermaid syntax rules** (or the diagram will fail): unique ids of letters and numbers only (never `end`); always quote labels; avoid `()`, `[]`, and `#` even inside quotes (write `PR 38`, not `PR #38`); paste raw Mermaid into the template, no fences.

## 6. PR type, before/after, and affected features

Pick exactly one PR type from the title, commit messages, and diff:
- **New feature** — added files or routes that introduce a capability
- **Improves a feature** — extends or changes an existing capability
- **Bug fix** — fix/bug keywords and a small diff
- **Removes a feature** — removed files, routes, or a capability
- **Refactor (no behaviour change)** — renames or moves with no behaviour change
- **Docs/config** — only markdown, yaml, or config

**Before and after** — two short plain-English lines, from a user or developer view of app behaviour: `Before: ...` then `After: ...`.

**Affected features** — list existing features that use the changed code. In the local repo, run `rg` for callers or imports of the changed functions and files. Use a short name (2–4 words) for each. Mark each **breaking**, **may break**, **changed**, or **safe**, and output them in that order (breaking first, safe last). Put any short reason in the `title` attribute only, not as visible text. If a change is breaking (removed or renamed public API, changed config or env, a DB migration, or a changed response shape), mark it **breaking** and add the reason in `title`. If nothing existing is touched, write: `No existing features affected (new code only)`.

## 7. Copy this style

Fake PR `#42` Add JWT login, `feature/jwt-login` → `main`, open, real code +201 / -6, total +281 / -6 because of one generated lockfile +80 / -0. Overlaps `src/api/auth.py` with open PR 38 Session refresh. Risk 9/10 high: auth +3, migration +2, deps +1, overlap +2.

PR type: New feature.
Before: The API had no JWT login, so users could not sign in with a token.
After: Users can sign in with a JWT. A users migration stores the new login data, and the user service wires it in.
Affected (pills, breaking first): Users database (breaking — adds a users migration); Auth API (may break — overlaps open PR 38 on auth.py); User service (changed).

Review path: ① users migration → ② auth → ③ user service → ④ tests.

```mermaid
flowchart TB
  HEAD["🌿 feature/jwt-login"] --> BASE["🎯 main"]

  subgraph PATH["Review path"]
    direction TB
    DB["① 🔥 users migration +40/-0"]
    AUTH["② 🔥 auth +80/-0"]
    USER["③ 🟡 user service +24/-6"]
    TEST["④ 🧪 test_auth +55/-0"]
    DB ==> AUTH
    AUTH ==> USER
    USER ==> TEST
  end

  DEPS["📦 requirements.txt +2/-0"]
  GEN["🤖 auto-generated 1 file +80/-0"]
  C38["⚠️ PR 38 Session refresh"]

  HEAD --> DB
  HEAD --> DEPS
  HEAD --> GEN
  AUTH -.-> C38

  click DB call showNode("DB")
  click AUTH call showNode("AUTH")
  click USER call showNode("USER")
  click TEST call showNode("TEST")
  click DEPS call showNode("DEPS")
  click GEN call showNode("GEN")

  classDef branch fill:#1e293b,stroke:#94a3b8,color:#e2e8f0
  classDef added fill:#14532d,stroke:#22c55e,color:#dcfce7
  classDef modified fill:#713f12,stroke:#eab308,color:#fef9c3
  classDef deleted fill:#7f1d1d,stroke:#ef4444,color:#fee2e2
  classDef tests fill:#1e3a8a,stroke:#3b82f6,color:#dbeafe
  classDef deps fill:#581c87,stroke:#a855f7,color:#f3e8ff
  classDef risky fill:#9a3412,stroke:#f97316,color:#ffedd5
  classDef generated fill:#1f2937,stroke:#64748b,color:#94a3b8,stroke-dasharray:5 5
  classDef conflict fill:#7f1d1d,stroke:#ef4444,color:#fecaca,stroke-dasharray:5 5

  class HEAD,BASE branch
  class DB,AUTH risky
  class USER modified
  class TEST tests
  class DEPS deps
  class GEN generated
  class C38 conflict

  linkStyle 1,2,3 stroke:#22d3ee,stroke-width:3px
```

## 8. Write the HTML file

1. Read `template.html` from the skill folder, usually `~/.claude/skills/prism/template.html`.
2. Replace these placeholders exactly:
   - `{{TITLE}}` — PR number and title. Example: `#42 Add JWT login`
   - `{{META}}` — HTML chips. The first chip is always the PR type badge (see below):

     ```html
     <span class="pr-type-badge type-new">New feature</span>
     <span class="chip">owner/repo</span>
     <span class="chip">#42</span>
     <span class="chip">by alice</span>
     <span class="chip">🌿 feature/jwt-login → 🎯 main</span>
     <span class="chip chip-state open">Open</span>
     <span class="chip">real code +201 / -6</span>
     <span class="chip chip-muted">total +281 / -6</span>
     ```

     State chip: `chip chip-state open`, `merged`, or `closed`.
   - PR type badge (goes inside `{{META}}`, first) — exactly one badge. Class: `type-new`, `type-improves`, `type-fix`, `type-removes`, `type-refactor`, or `type-docs`.

     ```html
     <span class="pr-type-badge type-new">New feature</span>
     ```

     Labels: New feature, Improves a feature, Bug fix, Removes a feature, Refactor (no behaviour change), Docs/config.
   - `{{BEFORE_AFTER}}` — two short plain-English lines:

     ```html
     <div class="before-after">
       <p><strong>Before:</strong> The API had no JWT login, so users could not sign in with a token.</p>
       <p><strong>After:</strong> Users can sign in with a JWT. A users migration stores the new login data, and the user service wires it in.</p>
     </div>
     ```

   - `{{AFFECTED}}` — existing features as one wrapping row of short-name pills, in this order: `is-breaking`, `may-break`, `changed`, `safe`. Put any reason in the `title` attribute only. If none:

     ```html
     <div class="affected">
       <h2>Affected features</h2>
       <p class="affected-empty">No existing features affected (new code only)</p>
     </div>
     ```

     Otherwise:

     ```html
     <div class="affected">
       <h2>Affected features</h2>
       <ul class="affected-list">
         <li><span class="feat-pill is-breaking" title="Adds a users migration">Users database</span></li>
         <li><span class="feat-pill may-break" title="Overlaps open PR 38 on auth.py">Auth API</span></li>
         <li><span class="feat-pill changed">User service</span></li>
       </ul>
     </div>
     ```

   - `{{SUMMARY}}` — exactly three `<li>` bullets: what changed, why it matters, and any risk or conflict.
   - `{{CONFLICTS}}` — overlaps in `<div class="conflicts-warn">...</div>`. Merged or closed: `<div class="conflicts-ok">This PR is already merged. Conflicts are resolved.</div>` (say "closed" when it is closed). Open with no overlap: `<div class="conflicts-ok">No conflicts found ✅</div>`.
   - `{{RISK}}` — use this shape (level class is `low`, `medium`, or `high` on both `risk-level` and `risk-fill`; fill width is score times 10%):

     ```html
     <div class="risk-meter" data-score="9" data-level="high">
       <div class="risk-head"><span class="risk-num">9</span><span class="risk-max">/10</span><span class="risk-level high">High</span></div>
       <div class="risk-bar"><div class="risk-fill high" style="width:90%"></div></div>
       <ul class="risk-reasons">
         <li>Touches auth and a new JWT login path</li>
         <li>Adds a users migration</li>
         <li>Updates requirements.txt</li>
         <li>Overlaps open PR 38 on auth</li>
       </ul>
     </div>
     ```

   - `{{REVIEW_PATH}}` — an `<ol class="review-steps">` of the path. Each item: `<li><span class="step-num">①</span><div><strong>module</strong><p>Why look here.</p></div></li>`
   - `{{DIAGRAM}}` — raw Mermaid only, no fences.
   - `{{FILES_JSON}}` — one JSON object, no fences. Keys are node ids. Value: `{"label":"auth","files":[{"path":"src/api/auth.py","add":80,"del":0,"status":"risky","generated":false}]}`. `status` is added, modified, deleted, tests, deps, risky, or generated. Use real paths when you have them; if you only have a module label, use that label as `path`. Do not invent paths.
   - Before writing, check that no `{{` text is left in the page. Every placeholder must be replaced.
3. Where to write it:
   - **Default (temporary):** write to a hidden folder in the current project: `./.prism/pr-<N>.html` (create the folder). Keep it out of git without touching tracked files: if inside a git repo, append `.prism/` to `$(git rev-parse --git-common-dir)/info/exclude` when it is not already there. Never edit `.gitignore`. It stays inside the project so the editor or Claude app preview can open it.
   - **Save only if asked:** if the input or chat says `save` (for example `/prism 741 save`) or the user asks to keep it, write to `./prism-output/pr-<N>.html` in the current working directory instead.
4. Do NOT open the file or a browser yourself. Never run `open`, `xdg-open`, or `start`. The user decides where to view it.

## 9. Reply in chat

Reply with only:

1. One line: what the PR does.
2. One line: main modules changed, with real-code +adds / -dels (and total if generated files were muted).
3. One line: risk score and conflict status.
4. A clickable link to the page, as a Markdown link with the absolute path, like `[🔺 Open PR #<N> map](file:///absolute/path/pr-<N>.html)`. Use the real absolute path of the file you wrote (use `pwd`). If it is the temporary copy, add: "Temporary view in `.prism/` (ignored by git). Run `/prism <N> save` to keep it in `prism-output/`." On the next line, also print the plain absolute path so it can be copied into any browser or editor preview. Then add one more line with a command the user can copy to open it, in a code block: `open <absolute path>` on macOS (`xdg-open` on Linux, `start` on Windows). Only show this command; never run it yourself.

Do not paste the Mermaid or a long report in chat.
