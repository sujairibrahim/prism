# Contributing to PRism

Thanks for helping! Bug reports, ideas, and pull requests are all welcome.

## Report a bug or suggest an idea

Open an [issue](../../issues/new/choose) and pick a form. For a bug, include the command you ran and what you expected to see. Please remove anything private, such as code from a private repo.

## Send a change

1. Fork the repo and create a branch.
2. Make your change. Keep it small and focused on one thing.
3. Test it:
   - Copy your version into your skills folder (`~/.claude/skills/prism`) and run `/prism` on a real PR.
   - If you changed `prism_collect.py`, check that `python3 -m py_compile prism_collect.py` passes and run it on a public PR, for example `python3 prism_collect.py cli/cli#12000`.
   - If you changed `template.html`, update `example.html` the same way and open it in a browser.
4. Open a pull request into `main` and fill in the short checklist.

All changes go through a pull request. `main` is protected, and the maintainer reviews and merges each PR.

## Keep it simple

PRism should stay easy to use. Prefer smart defaults over new options, and keep the README short. If a change adds a new command or option, explain in the PR why it's worth it.

## Code of conduct

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
