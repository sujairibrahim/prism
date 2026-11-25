# PRism

See what a pull request does at a glance. PRism turns a GitHub PR, or your own branch before you open one, into a visual page: a summary, a risk score, the order to review in, real conflicts with other PRs, and a clickable map of the changed modules.

![Example PRism page for fake PR #42 Add JWT login](example-page.png)

## Install

You need [Claude Code](https://claude.com/claude-code) or [Codex](https://developers.openai.com/codex), the [GitHub CLI](https://cli.github.com/) (`gh`, logged in), and Python 3.

For Claude Code:

```bash
git clone https://github.com/sujairibrahim/prism ~/.claude/skills/prism
```

For Codex:

```bash
git clone https://github.com/sujairibrahim/prism ~/.agents/skills/prism
```

To update later, run `git pull` in that folder.

## Use it

| Type this | What you get |
| --- | --- |
| `/prism 42` | A map of PR 42. A PR link works too. |
| `/prism` | A map of your current branch, before you open a PR, with a suggested PR description. |
| `/prism 42 since` | Only what changed since your last review. |
| `/prism 42 comment` | The map posted as a comment on the PR, so your team sees it. It asks before posting. |
| `/prism queue` | The PRs waiting on your review, riskiest first. |

In Codex, type `$prism` instead of `/prism`, or just ask, for example "map PR 42 with prism".

You get a reply with a link to the page. Pages go to a hidden `.prism/` folder that git ignores. Add `save` to any command to keep the page in `prism-output/` instead.

## What's on the page

- What the PR does, before and after, and which existing features it touches
- A risk score from 1 to 10, with the reasons
- A review path: which modules to read first, and why
- Conflicts with the base branch and other open PRs. Real conflicts and clean overlaps are shown apart.
- A map of the changed modules. Click one to see its files, and click a file to open its diff on GitHub.
- Lockfiles and other generated files, muted so they don't distract
- Light and dark mode

## Good to know

- **Run it from a local clone of the repo** for the best results. PRism can then check real merge conflicts and find code that calls the changed code. Anywhere else it still works, and the page says what it could not check. It never checks out a branch or changes your files.
- **The map needs internet** to load. Offline, the rest of the page still works.
- **Nothing is posted without your OK.** `comment` shows you the draft first.

<details>
<summary><strong>More options</strong></summary>

- `/prism 42 since abc1234` — changes since a given commit, instead of since your last review. If the commit is gone (after a force-push or rebase), PRism shows the full PR and says why.
- `/prism branch base=develop` — compare your branch with a different base branch. By default PRism uses the repo's default branch.
- `/prism branch +uncommitted` — include changes you have not committed yet. By default only commits are included, and PRism tells you how many files are uncommitted.
- `/prism queue all` — PRs waiting on you across every repo, not just this one.
- In author mode the reply includes a ready `gh pr create` command for you to run. PRism never runs it.

</details>

<details>
<summary><strong>How the risk score works</strong></summary>

The score starts at 1. "Lines" means lines changed, not counting generated files.

| Rule | Points |
| --- | --- |
| Sensitive code (auth, permissions, security, payments): under 50 lines | +1 |
| Sensitive code: 50-199 lines | +2 |
| Sensitive code: 200+ lines, or a new login, token, or permission flow | +3 |
| Migration that only adds (new tables, columns, indexes) | +1 |
| Migration that changes or drops existing data | +2 |
| Config or CI changes | +1 |
| Dependency manifest changes | +1 |
| Size: 300-999 / 1000-2999 / 3000+ lines | +1 / +2 / +3 |
| No tests changed (skipped for docs/config-only or under 20 lines) | +2 |
| Tests changed but thin (under a quarter of the other lines) | +1 |
| Tests changed alongside sensitive code or a migration, and not thin | −1 |
| Real conflict with the base branch or another open PR | +2 |
| Otherwise, another open PR touches the same files but merges cleanly | +1 |

The score is capped at 10. It is at least 2 when sensitive code or a migration changed. 1-3 is low, 4-6 medium, 7-10 high.

A small script, `prism_collect.py`, does all the counting and scoring, so the numbers are the same every run. The AI reads the code and writes the words.

</details>

<details>
<summary><strong>Post on every PR automatically (GitHub Actions, uses Claude Code)</strong></summary>

[examples/github-action/prism.yml](examples/github-action/prism.yml) runs PRism on every opened or updated PR and posts or updates one PRism comment. See [examples/comment-example.md](examples/comment-example.md) for what the comment looks like.

1. In your repo, add PRism to `.claude/skills/prism/` and commit it to the default branch:

   ```bash
   git clone --depth 1 https://github.com/sujairibrahim/prism .claude/skills/prism && rm -rf .claude/skills/prism/.git
   ```

2. Copy the workflow to `.github/workflows/prism.yml`:

   ```bash
   mkdir -p .github/workflows && cp .claude/skills/prism/examples/github-action/prism.yml .github/workflows/
   ```

3. Add your Anthropic API key as a repo secret named `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).

The comment is posted by `github-actions[bot]`. PRs from forks are skipped. Each run uses your Anthropic API credits.

</details>

<details>
<summary><strong>Run the script on its own</strong></summary>

Run it from the PRism folder. `prism_collect.py` prints the PR facts as JSON: files, modules, totals, tests, conflicts, and the risk score with reasons.

```bash
python3 prism_collect.py 42
python3 prism_collect.py 42 --since last
python3 prism_collect.py --branch
```

Run it with `--help` for all options.

</details>

## Contributing

Bug reports, ideas, and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
