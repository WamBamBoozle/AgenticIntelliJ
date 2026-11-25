# Agentic IntelliJ

Tools for agentic work in IntelliJ IDEA: many Claude Code sessions at once,
each project in its own IDE window and each session in a terminal tab there.
They start sessions with stable names their peers can address, share one sbt
server per checkout between the IDE and every session, keep the machine within
its memory, and bring everything back after a restart.

The repository also ships a Claude Code skill, `intellij-health`, for
troubleshooting IntelliJ: it reads the IDE's logs and the machine's memory use,
then reports what is wrong and what to do about it (see
[IDE log review and health check](#ide-log-review-and-health-check)). It works
on its own, without the rest of the setup. To use it from every project, install
it as a plugin from inside Claude Code:

```
/plugin marketplace add WamBamBoozle/AgenticIntelliJ
/plugin install intellij-health@agentic-intellij
```

Sessions started in a clone of this repository load it without installing.

Measured on a Mac (M3 Max, 36 GB), as the sum of each process's footprint in
`top` (which counts compressed and swapped memory): about ten sessions over
seven checkouts needed about 74 GB before this work, with 20 GB in swap. After
it, nine sessions over nine checkouts need about 34 GB, and swap is empty. Most
of the setup below exists to cut that number, or to make restarts cheap enough
that you can close things.

## Terms

- **Checkout:** a git working copy on disk, a clone or a worktree. Each one gets
  its own sbt server.
- **Project:** a checkout opened in IntelliJ, in a window of its own.
- **Claude session:** one Claude Code process in a terminal tab of a project's
  window, started with a `-n` name its peers can address.
- **Bench:** a project's window together with the Claude sessions in its
  terminal tabs. `bench open` starts one; `bench save <project>` and
  `restore <project>` close and reopen one.
- **IntelliJ:** the one IDE process that holds every bench.

## The IDE and every session share one sbt server, over BSP

sbt is the Scala build tool. Each sbt is a JVM of 1–2 GB, and since sbt 1.4 it
can stay running as a server that other programs connect to; `sbt --client`
sends commands to that server instead of starting a JVM of its own.

BSP, the Build Server Protocol, is how an IDE talks to a build tool: it asks
for the project's modules, source folders and dependencies, and has the build
tool compile and run tests. It does for builds what LSP, the Language Server
Protocol, does for language tooling. JetBrains
and the Scala Center created it in 2018, and sbt has a BSP server built in.

IntelliJ can load an sbt project in two ways:

- **sbt import** (`.idea/sbt.xml`), its original way. IntelliJ starts its own
  sbt to read the build, copies the structure into IntelliJ modules, and from
  then on compiles with its own compiler and runs its own sbt shell. That is a
  separate sbt JVM for the IDE, beside the ones terminals and Claude sessions
  start: up to three per checkout.
- **BSP import** (`.idea/bsp.xml`). IntelliJ runs the command in
  `.bsp/sbt.json` to reach the checkout's sbt server, and sbt does the building.

This repository makes the BSP import work in daily use, so the IDE, your
terminals and every Claude session in a checkout share one sbt server:

```
IntelliJ ─── BSP ──▶ .bsp/sbt.json → sbt-bsp → direnv exec . sbt -bsp ─┐
terminal ──────────▶ sbt --client ─────────────────────────────────────┼─▶ one sbt server
Claude sessions ───▶ sbt --client ─────────────────────────────────────┘    per checkout
```

- `sbt-bsp-setup` points `.bsp/sbt.json` at `sbt-bsp`, which starts sbt in the
  checkout's direnv environment; IntelliJ doesn't have your shell's environment
  when it starts sbt itself.
- `sbt/global.sbt` puts that file back after sbt rewrites it, which sbt does
  each time a server starts, and `git-hooks/post-checkout` sets up every new
  worktree.
- `intellij-bsp` switches IntelliJ's side: it writes `.idea/bsp.xml`, moves
  `.idea/sbt.xml` aside, and drops the modules the sbt import left behind.

Fewer sbt JVMs is a large part of the 74 GB → 34 GB saving. Sharing one server
also means the IDE, a terminal and a session reuse each other's compiles and
never compile the same checkout at once: their commands run one after another.
The [sbt section](#sbt-one-server-per-checkout) has the details.

## Platforms

Written and used on macOS. The shell setup and the sbt scripts run in bash
(3.2 or later) or zsh; the rest depends on the platform:

- **Portable:** the shared sbt server (`sbt-bsp`, `sbt-bsp-setup`,
  `sbt/global.sbt`, `git-hooks/post-checkout`), `SBT_OPTS` and the queue
  hook need only bash or zsh, sbt, git, direnv and the usual `realpath` and
  `shasum`. The skill's log scan also reads Linux's `~/.cache/JetBrains`.
- **macOS only:** `bench` and `intellij-bsp` drive
  IntelliJ windows and terminal tabs through AppleScript; `intellij` (a zsh
  script, which every Mac has) looks for the app in `/Applications` or
  `~/Applications` and IDE files under `~/Library`; the skill's memory snapshot
  uses macOS memory tools.
  Elsewhere these would need another way to open IDE windows and terminal tabs.

For how this compares with other tools for running many sessions, Claude Code
in JetBrains IDEs, session restore and IDE diagnostics, see
[PRIOR_ART.md](PRIOR_ART.md).

## Setup

This repository's `bin/` must be on your `PATH`; every command below is run by
name from there. The scripts find each other through their own location, so the
clone can live anywhere. Source the shell setup from `~/.bashrc` or `~/.zshrc`, after whatever
puts `claude` and `direnv` on your `PATH`:

```sh
source ~/src/AgenticIntelliJ/shell/agentic-intellij.sh
```

It adds `bin/` to `PATH`, sets `SBT_OPTS` (below), and installs the queue
hook that starts sessions in new IntelliJ terminals. Then:

- Optionally, set `BENCH_CLAUDE_ARGS` there to the `claude` flags a new
  session should start with, such as `--model opus`.
- For the shared sbt server: link `sbt/global.sbt` into `~/.sbt/1.0/`, run
  `sbt-bsp-setup <checkout>` once per Scala checkout, and copy
  `git-hooks/post-checkout` into each such repository's `.git/hooks/`.
- So that Claude sessions join that server instead of starting their own sbt,
  add this line to `~/.claude/CLAUDE.md`, which every session loads:

  ```
  @~/src/AgenticIntelliJ/claude/sbt-client.md
  ```

  (Or paste the file's contents there.) Without it, sessions run plain `sbt`
  and each starts a 1–2 GB JVM of its own.

## The pieces at a glance

| Tool | Job |
|---|---|
| `bench open <project>` | Start a bench: open one project in IntelliJ and resume its saved sessions, or start a new one, in terminals there |
| `intellij [paths]` | Start IntelliJ, cleaning up after the last run first; hand paths to it if it's already up |
| `bench save` / `restore` | Quit IntelliJ with every session recorded; later, reopen it and resume them all. Given a project, do it for that one bench |
| `bench prune` | Drop saved sessions whose directory is gone |
| `sbt-bsp`, `sbt-bsp-setup` | Make IntelliJ, Claude and you share one sbt server per checkout |
| `intellij-bsp` | Switch closed IntelliJ projects from sbt import to BSP |
| queue hook (`shell/agentic-intellij.sh`) | Runs queued session commands when a new IntelliJ terminal opens |

## Starting a bench: `bench open`

`bench open api` opens the project in IntelliJ and resumes the sessions saved
for it, with their original flags. `api` is a directory, or a name: a saved
session's `-n` name, or the name of a saved session's directory. With nothing
saved, it starts a new session named after the directory:

```
bench open ~/src/api                     # claude $BENCH_CLAUDE_ARGS -n api
bench open ~/src/api -- --add-dir ../lib # claude --add-dir ../lib -n api
```

Once a `bench save` has recorded that session, its flags come back with it.

It never types into a terminal. Instead it **queues** the command in
`~/.cache/bench/pending/<sha1 of the directory's real path>`, and the hook
in `shell/agentic-intellij.sh` runs it when a new IntelliJ terminal opens in that directory:

- The hook runs only in IntelliJ terminals (`TERMINAL_EMULATOR=JetBrains-JediTerm`).
- The queue file holds one command per line, because several sessions can share
  a directory. Each new terminal takes the first line and removes it, under a
  lock so two tabs opening at once don't take the same line.
- If no terminal picks the command up within a minute, `bench` raises the
  window and presses alt-F12 to open one.

**direnv.** The hook runs while your shell's rc file is still loading, before direnv's own
hook has fired, so a session started there wouldn't see the project's `.envrc`
(secrets, per-checkout `TMPDIR`, nix tools). Queued commands therefore start
with `eval "$(direnv export bash)"` (or `zsh`, whichever shell runs them). An unapproved `.envrc` stays unapproved;
`bench` warns instead of approving it.

## Starting IntelliJ: `intellij`

`intellij` owns the IDE process; `bench` calls it. `INTELLIJ_APP` pins
the IDE bundle to use.

- **IntelliJ already running:** it hands the paths to the IDE and touches
  nothing else.
- **IntelliJ not running:** it cleans up first, then launches the IDE with its
  output in `~/logs/idea.log`. The previous run's log is kept as
  `~/logs/idea_backup.log`, minus a noisy Settings Sync heartbeat.

The cleanup removes what earlier runs leave behind:

1. Helper processes still running from the IDE's bundle or cache folders:
   embedded-browser renderers, sbt shells, the Scala compile server, JPS
   builds. Toolbox and the shared JetBrains daemon are left alone.
2. The Kotlin compile daemon and its "client is running" marker files. The
   markers pile up (896 after one reboot), and while any exist the daemon never
   reaches its idle shutdown.
3. Claude sessions orphaned by a closed IntelliJ terminal.
4. The Settings Sync cache, to work around a JetBrains sync loop (only when
   online).
5. Old thread dumps, empty embedded-browser logs, JVM crash reports and heap
   dumps.

`intellij --dry-run` shows what would be cleaned and launched.
`intellij --clean-only` cleans without launching.

## Restarting without losing sessions: `bench`

```
bench save       # before a reboot or IDE update
bench restore    # after
bench show       # what's running now, and what was saved
bench prune      # drop saved sessions whose directory is gone
```

Given a project, a directory or a name as for `bench open`, `save` and
`restore` act on that one bench and leave IntelliJ and the other benches
running:

```
bench save <project>     # record the bench's sessions, close its window
bench restore <project>  # reopen the bench and resume them
```

**`save`** records every Claude session running in an IntelliJ terminal into
`~/.cache/bench/state.json`: name, session ID, directory, and
original flags. It then stops the sessions and quits IntelliJ.

- It refuses while a session is busy; `--force` overrides.
- It works from inside a Claude session in IntelliJ: the part that stops
  sessions and quits the IDE detaches first, so it survives.
- Progress goes to `~/logs/bench.log`.
- For one bench, it closes the window with **File → Close Project** and
  keeps the record in `~/.cache/bench/projects/`, apart from the
  whole-IDE save. If the window doesn't close (a dialog is waiting), nothing is
  stopped.

**`restore`** queues each session's resume command (`claude <original flags>
--resume <id> -n <name>`) for its directory and starts IntelliJ through
`intellij`. Each terminal tab IntelliJ reopens picks up one queued session.

- For one bench, it uses the newer of that bench's own save and its part of
  the whole-IDE save.
- Sessions already running, or whose directory is gone, are skipped.
  `bench show` marks the gone ones, and `bench prune` drops them, deleting a
  bench's own save when none of its sessions is left.
- If a directory had more sessions than IntelliJ reopened tabs, open another
  terminal tab there (**+**) and the next session starts in it.

**Let IntelliJ quit on its own.** If it is still showing a confirmation dialog
when you reboot, it never saves its window layout, and only one terminal tab
per project comes back.

## sbt: one server per checkout

Every plain `sbt` command starts a new 1–2 GB JVM. Before this work, IntelliJ's
sbt shell, each Play `run`, and every `sbt test` from a Claude session each had
their own. Now one sbt server per checkout serves all of them.

```
IntelliJ ──BSP (JSON-RPC)──▶ sbt -bsp client (small)
                                      │  socket listed in project/target/active.json
Claude:  sbt --client "test" ───────▶ sbt server (the one JVM per checkout)
You:     sbt --client ──────────────▶     compiles, tests, holds the build
```

The first client to arrive starts the server in the background. Every later
client connects to it.

### Claude sessions: `sbt --client`

[`claude/sbt-client.md`](claude/sbt-client.md), imported from
`~/.claude/CLAUDE.md` (see [Setup](#setup)), tells every session to run one-off
commands as `sbt --client "testOnly …"`, which joins the checkout's server or
starts it, and to `sbt --client shutdown` only servers it started. Plain `sbt`
is kept for long-running processes such as Play `run`.

### IntelliJ: import over BSP, not as an sbt project

IntelliJ talks to the server through BSP (Build Server Protocol), a standard way
for an editor to ask a build tool to load, compile and test. IntelliJ reads the
command to run from `<build>/.bsp/sbt.json`.

That file normally runs `java … sbt-launch.jar -bsp` directly. A server
started that way inherits IntelliJ's environment, not the project's, and every
`sbt --client` test that shares it would run without the `.envrc` secrets. So
`.bsp/sbt.json` points at **`sbt-bsp <build dir>`** instead (by absolute path,
since IntelliJ doesn't use your shell's `PATH`), which runs
`direnv exec . sbt -bsp`. Whoever starts the server, it has the project's
environment.

**Setting up a checkout:** run `sbt-bsp-setup <checkout>`. It writes
`.bsp/sbt.json` for each sbt build in it (the root and builds one or two levels
down, such as `backend/`) and
marks the team-tracked `.idea/sbt.xml` as skip-worktree, so your switch to BSP
never shows up in `git status`. Undo with
`git update-index --no-skip-worktree .idea/sbt.xml`. A local (uncommitted)
`post-checkout` hook in each repo (`git-hooks/post-checkout` here) runs
`intellij-bsp`, which runs it, on every new git worktree (see below).

sbt itself rewrites `.bsp/sbt.json` every time a server starts. `sbt/global.sbt`
undoes that: in builds `sbt-bsp-setup` has prepared, it waits for the rewrite
and runs `sbt-bsp-setup` again.

**Switching a project to BSP in IntelliJ** (once per window):

1. **sbt** tool window → right-click the project → **Unlink sbt Project**.
2. **File → Close Project**.
3. On the Welcome screen, **Open** the folder and choose **BSP project**; if
   asked for a tool, choose **sbt**.

*File → New → Project from Existing Sources* doesn't work for a folder that's
already open: IntelliJ just refocuses the window.

`intellij-bsp <project dir>` does the same switch from the command line for a
closed project. To switch an open one without losing its sessions:

```
bench save <dir> && intellij-bsp <dir> && bench restore <dir>
```

`intellij-bsp` also removes the modules the sbt import created, which a
manual switch leaves behind. If they stay, they keep claiming the source
folders, and the Scala plugin shows "Code insight is unavailable because the sbt
project is not loaded" even though the BSP import is fine. To clean up a
project switched earlier, close it and run `intellij-bsp` on it again, or remove
the old modules in **File → Project Structure → Modules**.

On a checkout IntelliJ hasn't opened yet, such as a new worktree, run
`intellij-bsp` before the first open. If the repository keeps `.idea/sbt.xml`
in git, it switches that; if not, it links the sbt builds it finds on disk (the
root and one or two levels down, as `sbt-bsp-setup` looks). Either way the
first open imports over BSP. The `post-checkout` hook does this for every new
worktree. A checkout IntelliJ has already opened without
linking sbt (it has `.idea/workspace.xml` but no `sbt.xml`) is left alone. A
worktree tool can run it after creating the worktree: it exits 0 when it
switched or had nothing to do, and 1 when it refused (the project is open, or
the path is not a directory) or failed. A refusal changes nothing. A failure
partway can leave what `sbt-bsp-setup` already did (`.bsp/`, and git's
skip-worktree on `.idea/sbt.xml`) in place; rerun it once the cause is fixed.

Settings you added by hand to the sbt import's modules, such as a Python
interpreter facet, go with them; `intellij-bsp` names each one, and you set it
up again on the BSP module of the same directory.

Check it afterwards: `.idea/bsp.xml` exists, `.bsp/sbt.json` still runs
`sbt-bsp` (IntelliJ can regenerate it; rerun `sbt-bsp-setup` if so), and
`ps` shows one sbt server for the checkout plus a small `-bsp` client.

### Seeing sbt's output

The server runs in the background with its output going to `/dev/null`, and
each client sees only the output of its own commands (tested: an idle
`sbt --client` shows nothing when another client runs a command).

| To see | Look at |
|---|---|
| IntelliJ's builds and imports | the **Build** and **BSP** tool windows |
| Your own commands | `sbt --client` in a terminal: an interactive prompt on the shared server |
| A Claude session's commands | that session's terminal |
| The last run of any task, whoever ran it | `sbt --client "last admin/compile"`, or `<module>/target/streams/…/out` |

### Idle JVMs give memory back

`shell/agentic-intellij.sh` sets, for every sbt (sdkman's and nix's both read it):

```
export SBT_OPTS="-XX:+IgnoreUnrecognizedVMOptions -XX:+UseCompactObjectHeaders -XX:G1PeriodicGCInterval=60000"
```

- `IgnoreUnrecognizedVMOptions`: checkouts build on different JDKs, and without
  it a JDK that doesn't know one of the other flags refuses to start at all.
- `UseCompactObjectHeaders`: Java 25 can shrink every object's header from 12
  to 8 bytes, and sbt and the Scala compiler allocate enough small objects that
  this cuts their heap noticeably. Older JDKs skip it.
- `G1PeriodicGCInterval=60000`: an sbt server sits idle most of the day holding
  the heap its last compile grew to; a collection every idle minute hands that
  unused memory back to macOS.

Use plain `-XX:` flags, not `-J-XX:`: older sbt launchers pass `SBT_OPTS` to
java unchanged.

## Other memory savings

- **Junie and the AI Assistant are disabled.** They can't use a Claude Team
  license, and Junie ran several agent processes per window. They're listed in
  `disabled_plugins.txt` in the IDE's config folder, with Junie's RPC and MCP
  exposure also turned off in `idea.vmoptions`.
- **Embedded browser in-process:** `-Djcef.remote.enabled=false` in
  `idea.vmoptions`, after crashes in the out-of-process browser helper.
- **MCP servers without local processes:** each Claude session starts its own
  copy of every local MCP server. context7 now uses its hosted HTTP endpoint
  (`claude mcp add --transport http -s user context7 https://mcp.context7.com/mcp`),
  and a local proxy that duplicated a claude.ai connector was removed. Servers
  nobody uses are turned off with `disabledMcpjsonServers` in
  `~/.claude/settings.json`, which leaves the team's `.mcp.json` alone.
- **Databases in Docker:** MongoDB takes about half of Docker's memory for its
  cache unless capped (`--wiredTigerCacheSizeGB 0.5`), and Elasticsearch takes a
  large heap unless given one (`ES_JAVA_OPTS=-Xms512m -Xmx512m`).
- **Keep worktrees out of IntelliJ:** each worktree opened as its own window
  costs another index and sbt server. Let sessions work in worktrees from their
  terminal, and open one in IntelliJ only to review it.

## IDE log review and health check

When `intellij` starts the IDE and finds a previous log, it saves it as
`~/logs/idea_backup.log` and opens it in the IDE, so you or a Claude session
can review it.

For a fuller check, ask a Claude session how IntelliJ or the machine is doing:
any session once the plugin is installed (see the top of this page), or one
started in this repository. The `intellij-health` skill
(`plugins/intellij-health/`) summarizes the IDE's log and measures memory by process: the IDE's heap, sbt
servers and BSP clients per checkout, leftover daemons, and MCP servers
duplicated across Claude sessions.

## Still to do

- Decide whether to run each checkout's sbt server in a visible terminal tab
  instead of the background (untested: whether that console shows other
  clients' commands).

## Files

| Path | What |
|---|---|
| `bin/intellij` | IDE launcher and cleanup |
| `bin/bench` | open, save, restore and prune benches |
| `bin/intellij-sessions` | the old name for `bench`; runs it |
| `bin/sbt-bsp`, `bin/sbt-bsp-setup` | BSP launcher and per-checkout setup |
| `bin/intellij-bsp` | switch closed IntelliJ projects from sbt import to BSP |
| `sbt/global.sbt` | sbt global hook that keeps `.bsp/sbt.json` on `sbt-bsp` |
| `git-hooks/post-checkout` | runs `intellij-bsp` on each new worktree, so IntelliJ opens it over BSP |
| `shell/agentic-intellij.sh` | `PATH`, `SBT_OPTS`, the queue hook |
| `plugins/intellij-health/` | Claude Code plugin with the `intellij-health` skill: IDE log and memory health check |
| `.claude-plugin/marketplace.json` | makes this repository a plugin marketplace |
| `.claude/skills/intellij-health` | symlink, so sessions in this repository load the skill without installing |
| `claude/sbt-client.md` | instructions that make Claude sessions use `sbt --client` |
| `PRIOR_ART.md` | related projects and how this one differs |
| `AGENTS.md`, `CLAUDE.md` | instructions for coding agents working in this repository |
| `~/.claude/CLAUDE.md` | imports `claude/sbt-client.md`, so every session uses `sbt --client` |
| `~/.cache/bench/pending/` | queued session commands, one file per directory |
| `~/.cache/bench/state.json` | the last saved set of sessions |
| `~/.cache/bench/projects/` | the last save of each bench saved on its own |
| `~/logs/idea.log`, `~/logs/idea_backup.log`, `~/logs/bench.log` | logs |
