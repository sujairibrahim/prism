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
- Optional: a Markdown comment posted on the PR, so the whole team sees the same map

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
/prism <PR number or URL> [save] [comment]
```

Examples:

```text
/prism 42
/prism https://github.com/OWNER/REPO/pull/42
/prism 42 save
/prism 42 comment
```

By default, the page is written to `./.prism/pr-<N>.html` and kept out of git. Add `save` to write it to `./prism-output/` instead.

Open the page in a browser, or copy the `open` command from the chat reply.

## Share it on the PR

Add `comment` to also write a PR comment to `./.prism/pr-<N>-comment.md`:

```text
/prism 42 comment
```

The comment has the title, PR type, before and after, the risk score with reasons, conflicts, the review path, the PR map as a Mermaid block that GitHub draws, and a collapsed list of modules and files. See [examples/comment-example.md](examples/comment-example.md) for the fake PR #42.

Claude shows you the draft and asks before posting, because the comment is public under your name. If you say yes:

- If the PR already has a PRism comment (it starts with the hidden marker `<!-- prism -->`), Claude updates it.
- Otherwise Claude adds a new comment with `gh pr comment`.

So each PR keeps one PRism comment, updated in place. The comment map is not clickable; the HTML page still is.

## Post on every PR with GitHub Actions

[examples/github-action/prism.yml](examples/github-action/prism.yml) runs PRism on every opened or updated PR with [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action) and posts or updates the comment.

Run these from the root of your repo. `PRISM` is where you have this PRism folder.

1. Commit the skill to your repo's default branch:

   ```bash
   PRISM=path/to/prism
   mkdir -p .claude/skills/prism
   cp "$PRISM/SKILL.md" "$PRISM/template.html" .claude/skills/prism/
   ```

   It must be on the default branch: on PR runs the action loads `.claude/` from the base branch, not from the PR.
2. Copy the workflow:

   ```bash
   mkdir -p .github/workflows
   cp "$PRISM/examples/github-action/prism.yml" .github/workflows/prism.yml
   ```

3. Add your Anthropic API key as a repo secret named `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).

Notes:

- The workflow passes `comment post` to the skill. `post` means "already approved", so it posts without asking. Only use `post` where you mean it.
- The comment is posted by `github-actions[bot]` with the workflow token (`pull-requests: write`, `contents: read`). No Claude GitHub App is needed.
- The HTML page is uploaded as a workflow artifact named `prism-pr-<N>`.
- PRs from forks are skipped by the action by default, so they get no comment.
- Each run uses your Anthropic API credits.
