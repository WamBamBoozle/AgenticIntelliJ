# Prior art

What already existed when this repository was published (November 2026), and
how this repository differs. Every project linked here was looked at, but none
was installed or tried; descriptions come from their own pages.

In short: most tools for many Claude Code sessions make a terminal multiplexer
or their own app the place where sessions live. This repository keeps IntelliJ
IDEA as that place, one window per project, and adds what that needs: a shared
sbt server between the IDE and the sessions, restoring sessions into IDE
terminal tabs, and a health check for the IDE and the machine under that load.

## Running many sessions

- [Claude Squad](https://github.com/smtg-ai/claude-squad) runs each agent in a
  tmux session with its own git worktree, behind a terminal UI.
- [CCManager](https://github.com/kbwo/ccmanager) does the same without tmux,
  for many agent CLIs, and can restore sessions after a restart.
- [Crystal, now Nimbalyst](https://github.com/stravu/crystal), is a desktop app
  for parallel sessions in git worktrees. Conductor is a macOS app in the same
  vein, and Anthropic's Claude desktop app also runs sessions side by side.

These organise work by task, usually a worktree per task. Here the unit is the
project: each checkout has its IDE window, its sbt server and its sessions,
and sessions in other checkouts are asked rather than duplicated (see
[agentic-development.html](agentic-development.html)).

## Claude Code inside JetBrains IDEs

- Anthropic's [Claude Code plugin](https://plugins.jetbrains.com/plugin/27310-claude-code-beta-)
  connects Claude Code running in a terminal to the IDE.
- IntelliJ IDEA has a [built-in MCP server](https://www.jetbrains.com/help/idea/mcp-server.html)
  since 2025.2, giving sessions IDE tools: search, inspections, run
  configurations, refactoring.
- GUI plugins replace the terminal with a chat panel:
  [Claude Code Plus](https://github.com/touwaeriol/claude-code-plus),
  [ClawDEA](https://github.com/adobe/ClawDEA),
  [claude-code-intellij](https://github.com/BHRother/claude-code-intellij).

This repository uses the first two as they are and keeps sessions in plain
IntelliJ terminal tabs.

## Restoring sessions after a restart

- [Claude Session Manager](https://github.com/JendaT/intellij-claude-session-manager)
  is the closest match: an IntelliJ plugin that binds Claude sessions to
  terminal tabs and resumes them when the project reopens. It needs IntelliJ
  2026.1's reworked terminal and installs Claude Code hooks.
- For tmux: [tmux-assistant-resurrect](https://github.com/timvw/tmux-assistant-resurrect)
  and its relatives record session ids with a hook and run `claude --resume`
  in each restored pane. [claude-session-restore](https://github.com/Supersynergy/claude-session-restore)
  does it for several terminal apps.

`intellij-sessions` differs in that it also shuts IntelliJ down and starts it
again, needs no IDE plugin or Claude Code hook (it reads the session files
Claude Code already writes), and restores the sessions' original flags,
including their `-n` names. It is macOS only.

## Sessions talking to each other

- Claude Code has [cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
  built in (`ListAgents`, `SendMessage`) since v2.1.224, and experimental
  [agent teams](https://code.claude.com/docs/en/agent-teams) for sessions one
  lead spawns and supervises.
- [MCP Agent Mail](https://github.com/Dicklesworthstone/mcp_agent_mail) adds
  inboxes, threads and file leases across projects over MCP.

This repository adds no messaging of its own. It starts each session with a
stable `-n` name so peers can keep addressing it across restarts, and the essay
in [agentic-development.html](agentic-development.html) describes how to use
the built-in messaging between repositories.

## One sbt server for the IDE and every session

sbt's own documentation describes the pieces: since sbt 1.4 a running server
writes `.bsp/sbt.json`, IntelliJ connects through it, and `sbt --client` in a
terminal joins the same server ([IDE integration](https://www.scala-sbt.org/1.x/docs/IDE.html),
[importing into IntelliJ](https://www.scala-sbt.org/2.x/docs/en/recipes/import-to-intellij.html)).
What I didn't find written up is making that hold up in daily use: a server
that IntelliJ starts lacks the project's direnv environment (JetBrains issue
[SCL-17661](https://youtrack.jetbrains.com/issue/SCL-17661) asks for
environment variables on sbt builds), and sbt rewrites `.bsp/sbt.json` each time
a server starts. `sbt-bsp`, `sbt/global.sbt` and `git-hooks/post-checkout`
handle both, for every checkout and worktree.

## Memory with many sessions

Claude Code issues report the same problem this repository started from:
memory growing with each open session ([#88524](https://github.com/anthropics/claude-code/issues/88524),
[#63318](https://github.com/anthropics/claude-code/issues/63318)) and every
session starting its own copy of each MCP server
([#28860](https://github.com/anthropics/claude-code/issues/28860)). Write-ups
such as [sharing MCP servers between sessions](https://tskulbru.dev/posts/claude-code-shared-mcp-servers/)
take the proxy route. This repository's advice (README, "Other memory
savings") is to use a server's hosted HTTP endpoint instead of a local process
and to turn off servers nobody uses; the health check finds duplicated ones.

## IDE diagnostics

- JetBrains' [IntelliJ Log Analyzer](https://github.com/JetBrains/IntelliJ-Log-Analyzer)
  displays the bundle from **Help | Collect Logs and Diagnostic Data**:
  `idea.log`, thread dumps, indexing diagnostics. Last updated in 2022.
- IntelliJ's [Activity Monitor](https://www.jetbrains.com/help/idea/activity-monitor.html)
  shows CPU use by subsystem and plugin, live.
- The IntelliJ source tree has a [`debugging` skill](https://github.com/JetBrains/intellij-community/tree/master/.claude/skills/debugging)
  for agents working on IntelliJ itself: how to search `idea.log` and
  investigate freezes.

`intellij-health` is for people using the IDE rather than developing it. It
reads `idea.log` and measures memory across the IDE, sbt servers, Kotlin
daemons, MCP servers and Claude sessions, separates the patterns that matter
from known noise, and says what to do about each.
