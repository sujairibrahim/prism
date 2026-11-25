# PRism 🔺

PRism turns a GitHub pull request into a visual HTML page, so you can see what the PR does at a glance.

The page includes:

- A short summary
- The PR type (new feature, bug fix, and so on)
- Before and after
- Affected features
- A risk meter from 1 to 10
- A suggested review path
- Conflicts with other open PRs
- A Mermaid PR map — click a module to see its files
- Auto-generated files, shown muted on the map
- Light and dark mode

![Example PRism page for fake PR #42 Add JWT login](example-page.png)

## Install

You need the [GitHub CLI](https://cli.github.com/) (`gh`) installed and logged in.

Copy these two files into your Claude Code skills folder:

```bash
mkdir -p ~/.claude/skills/prism
cp SKILL.md template.html ~/.claude/skills/prism/
```

## Usage

In Claude Code, run:

```text
/prism <PR number or URL> [save]
```

Examples:

```text
/prism 42
/prism https://github.com/OWNER/REPO/pull/42
/prism 42 save
```

By default, the page is written to `./.prism/pr-<N>.html` and kept out of git. Add `save` to write it to `./prism-output/` instead.

Open the page in a browser, or copy the `open` command from the chat reply.

The page loads Mermaid (for the PR map) and its fonts from a CDN, so it needs an internet connection. Offline, the PR map shows a short message instead, and the rest of the page still works: the summary, risk meter, review path, and a list of modules you can click to see their files. Fonts fall back to your system fonts.

For the best "Affected features" check, run `/prism` from a local clone of the PR's repo. Otherwise PRism cannot search for callers, so it reads affected features from the diff only and says so on the page.

## How the risk score works

The score starts at 1. PRism adds or subtracts points using only file paths and line counts. "Lines" means real lines changed (adds + dels), not counting auto-generated files.

| Rule | Points |
| --- | --- |
| Sensitive code (auth, permissions, security, payments): under 50 lines | +1 |
| Sensitive code: 50-199 lines | +2 |
| Sensitive code: 200+ lines, or a new login, token, or permission flow | +3 |
| Migration that only adds (new tables, columns, indexes) | +1 |
| Migration that changes or drops existing data | +2 |
| Config or CI changes | +1 |
| Dependency manifest changes | +1 |
| Size of real code: 300-999 / 1000-2999 / 3000+ lines | +1 / +2 / +3 |
| No tests changed (skipped for docs/config-only or under 20 lines) | +2 |
| Tests changed but thin (under a quarter of the other real lines) | +1 |
| Tests changed alongside sensitive code or a migration, and not thin | −1 |
| Already conflicts with the base branch | +2 |
| Otherwise, overlaps files with another open PR | +1 |

The score is capped at 10. The lowest score is 1, or 2 when sensitive code or a migration changed. Levels: 1-3 low, 4-6 medium, 7-10 high. The page lists each rule that scored, with its points.
