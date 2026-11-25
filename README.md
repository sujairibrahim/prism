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
- Re-review mode: only what changed since your last review
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
/prism <PR number or URL> [since [sha]] [save]
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
