# PRism 🔺

PRism turns a GitHub pull request into a visual HTML page, so you can see what the PR does at a glance. It also works on your own branch before you open a PR.

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
- A suggested PR description, in author mode
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
/prism [branch] [base=<name>] [+uncommitted] [save]
```

Examples:

```text
/prism 42
/prism https://github.com/OWNER/REPO/pull/42
/prism 42 save
```

By default, the page is written to `./.prism/pr-<N>.html` and kept out of git. Add `save` to write it to `./prism-output/` instead.

Open the page in a browser, or copy the `open` command from the chat reply.

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
