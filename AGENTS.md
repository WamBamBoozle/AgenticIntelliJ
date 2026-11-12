# AGENTS.md

Instructions for coding agents working in this repository. People should start
with [README.md](README.md).

## What this is

Tools for running many Claude Code sessions inside IntelliJ IDEA, plus a Claude
Code plugin, `intellij-health`, that checks the IDE's logs and the machine's
memory. Shell scripts, Python 3 (standard library only) and one sbt file; there
is no build.

| Path | What |
|---|---|
| `bin/` | the commands, run by name with `bin/` on `PATH` |
| `shell/agentic-intellij.sh` | sourced from `~/.bashrc` or `~/.zshrc`: `PATH`, `SBT_OPTS`, the hook that starts queued sessions |
| `sbt/global.sbt`, `git-hooks/post-checkout` | keep each checkout's BSP connection on `bin/sbt-bsp` |
| `plugins/intellij-health/` | the plugin; its skill is in `skills/intellij-health/` |
| `.claude-plugin/marketplace.json` | lists the plugin so `/plugin marketplace add` can find it |
| `.claude/skills/intellij-health` | symlink into the plugin, so sessions here load the skill |
| `agentic-development.html` | an essay on sessions working together; not code |

## Platforms

- Scripts in `bin/` find each other through their own real path; never hard-code
  where this repository or its `bin/` lives.
- `shell/agentic-intellij.sh`, `bin/sbt-bsp`, `bin/sbt-bsp-setup` and
  `bin/load-project` must run in bash 3.2 (macOS's `/bin/bash`) and, for the
  shell file, in zsh too. No `mapfile`, associative arrays or zsh-only syntax.
- `bin/intellij` is zsh and macOS only. `load-project`, `intellij-sessions`,
  `intellij-bsp` and the skill's `memory_snapshot.py` use AppleScript or macOS
  memory tools.

## Checking a change

There are no tests. Check what you touched:

```sh
bash -n bin/load-project bin/sbt-bsp bin/sbt-bsp-setup shell/agentic-intellij.sh
/bin/bash -n bin/sbt-bsp-setup            # macOS's bash 3.2
zsh -n shell/agentic-intellij.sh bin/intellij
python3 -m py_compile bin/intellij-bsp bin/intellij-sessions \
  plugins/intellij-health/skills/intellij-health/scripts/*.py
claude plugin validate . && claude plugin validate plugins/intellij-health
```

Read-only and safe to run: `load-project --list`, `load-project --dry-run <name>`,
`intellij-sessions show`, `intellij-sessions save|restore --dry-run`, `--help` on
any command, and both skill scripts.

## Ask before running

These change the machine or other sessions; run them only when the user asks:

- `intellij` (starts IntelliJ and cleans up after its last run),
  `intellij-sessions save|restore` (shuts the IDE down, restarts sessions),
  `load-project <name>` (opens a window, starts a session).
- `sbt-bsp-setup`, `intellij-bsp` (rewrite a checkout's `.bsp/` and `.idea/` files).
- Killing processes or changing settings that the health check recommends.

## Conventions

- Keep docs and examples generic: no employer, product, repository or ticket
  names, no paths under a real home directory, no secrets.
- `tmp/` is ignored by git and holds local working files; don't add it.
- When the plugin changes, bump `version` in both
  `plugins/intellij-health/.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json`; `claude plugin tag plugins/intellij-health`
  then creates the release tag.
