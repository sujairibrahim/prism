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

Counting lines, muting generated files, grouping modules, finding overlaps, and scoring risk are done by a small script, `prism_collect.py`. So the numbers are the same every run, and big PRs stay fast. Claude reads the code and writes the words.

![Example PRism page for fake PR #42 Add JWT login](example-page.png)

## Install

You need the [GitHub CLI](https://cli.github.com/) (`gh`) installed and logged in, and Python 3 (standard library only).

Copy these three files into your Claude Code skills folder:

```bash
mkdir -p ~/.claude/skills/prism
cp SKILL.md template.html prism_collect.py ~/.claude/skills/prism/
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

## The collector script

You can also run the script on its own. It prints one JSON object with the PR details, every file and its flags, the map modules, totals, tests, overlaps with other open PRs, and the risk score with reasons:

```bash
python3 ~/.claude/skills/prism/prism_collect.py 42
python3 ~/.claude/skills/prism/prism_collect.py https://github.com/OWNER/REPO/pull/42
python3 ~/.claude/skills/prism/prism_collect.py 42 --repo OWNER/REPO
```

Options: `--save FILE` writes the full JSON to a file and prints a shorter view, `--no-overlaps` skips the open-PR check, and `--max-nodes N` changes the map size (default 10). If `gh` is missing or not logged in, it prints an error JSON and exits with code 2 or 3.
