# PRism 🔺

PRism turns a GitHub pull request into a visual HTML page, so you can see what the PR does at a glance. It also works on your own branch before you open a PR.

The page includes:

- A short summary
- The PR type (new feature, bug fix, and so on)
- Before and after
- Affected features
- A risk meter from 1 to 10
- A suggested review path — each step opens its module's files or jumps to its diff
- Real conflict check against the base branch and other open PRs: real conflicts and clean overlaps are shown apart
- A Mermaid PR map — click a module to see its files
- Every file links straight to its diff on GitHub
- Auto-generated files, shown muted on the map
- Re-review mode: only what changed since your last review
- A suggested PR description, in author mode
- Light and dark mode

![Example PRism page for fake PR #42 Add JWT login](example-page.png)

## Install

You need the [GitHub CLI](https://cli.github.com/) (`gh`) installed and logged in.

For the real conflict check, run `/prism` inside a full (not shallow) local clone of the PR's repo, with git 2.38 or newer. PRism fetches PR heads into private `refs/prism/*` refs, runs `git merge-tree`, and deletes those refs again. It never checks out a branch or touches your working tree. Anywhere else, it falls back to file overlap only and says so on the page.

Copy these two files into your Claude Code skills folder:

```bash
mkdir -p ~/.claude/skills/prism
cp SKILL.md template.html ~/.claude/skills/prism/
```

## Usage

In Claude Code, run:

```text
/prism <PR number or URL> [since [sha]] [save]
/prism [branch] [base=<name>] [+uncommitted] [save]
```

Examples:

```text
/prism 42
/prism https://github.com/OWNER/REPO/pull/42
/prism 42 save
/prism 42 since
/prism 42 since abc1234
```

By default, the page is written to `./.prism/pr-<N>.html` and kept out of git. Add `save` to write it to `./prism-output/` instead.

### Re-review: only what changed

Add `since` to see only the changes since your last review on the PR. Add `since <sha>` to see the changes since a given commit. A banner at the top shows the starting commit and how many new commits there are. The map, modules, risk, and review path cover only the new changes, and a muted chip shows the full-PR totals. The page is written to `pr-<N>-since-<shortsha>.html`.

If you never reviewed the PR, or your review commit is gone after a force-push or rebase, PRism says so and shows the full PR. GitHub lists at most 300 changed files for this view.

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
| Real conflict with the base branch or another open PR (or GitHub says it already conflicts) | +2 |
| Otherwise, only a clean overlap: another open PR touches the same files but merges cleanly | +1 |

The score is capped at 10. The lowest score is 1, or 2 when sensitive code or a migration changed. Levels: 1-3 low, 4-6 medium, 7-10 high. The page lists each rule that scored, with its points.

## Author mode: before you open a PR

Run PRism on your own branch to see the same page before a PR exists:

```text
/prism
/prism branch
/prism branch base=develop
/prism branch +uncommitted
```

- If your current branch already has an open PR, PRism uses that PR.
- Otherwise it compares your branch with the base branch (`origin/HEAD`, else `main`, else `master`, or `base=<name>`). You don't need `gh` for this; without it, PRism skips the check for overlapping open PRs.
- Only committed work is included. Uncommitted changes are counted and mentioned. Add `+uncommitted` to include them.
- The page shows a "Draft (no PR yet)" chip and a suggested PR title and description with Copy buttons.
- It writes `./.prism/branch-<branch>.html` and `./.prism/branch-<branch>-pr.md`, and the chat reply gives a ready `gh pr create ... --body-file` command. PRism never runs it; you do.

You need to be in a git repo for author mode. Outside one, PRism asks for a PR number or link.
