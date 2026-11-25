# Security Policy

## Report a security problem

Please do not report security problems in a public issue.

Instead, use GitHub's private reporting: go to the [Security tab](../../security) of this repo and click **Report a vulnerability**. Only the maintainer can see the report.

Please include what you found, how to reproduce it, and what could go wrong. You'll get a reply as soon as possible.

## What counts

PRism runs `gh` and `git` on your machine and can post comments on pull requests. Examples of security problems:

- PRism changes your branches, files, or git history (it should never do this)
- PRism posts a comment without asking (outside the `post` option for GitHub Actions)
- A pull request's title, body, or file names can make PRism run unexpected commands
- The page or the comment leaks data it should not show

## Supported versions

Only the latest version on `main` gets fixes.
