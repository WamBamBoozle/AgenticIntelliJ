# Interpreting the snapshot and the log

Patterns seen in practice on an IntelliJ + many-Claude-sessions Mac, what they mean, and what fixed them. Check a finding against this list before reporting it.

## Contents
- Memory: sbt and BSP
- Memory: other JVMs
- Memory: MCP servers and Claude sessions
- Memory: the IDE, the system, other apps
- Log: real problems
- Log: known noise

## Memory: sbt and BSP

**Expected:** one sbt server JVM per Scala checkout that is in use (typically 0.8–1.8 GB footprint), plus one small `sbt-bsp-client` JVM per checkout open in the IDE (~220 MB). The IDE and every `sbt --client` share that one server. Servers start lazily, so a fresh reboot shows none.

**Duplicate sbt JVMs in one checkout** (`duplicate_sbt` in the snapshot, `!!` line in the report). Causes, most common first:
- A session or script ran plain `sbt …` for a one-off task instead of `sbt --client …`. Plain `sbt` starts a new 1–2 GB JVM and reloads the build. Fix: use `sbt --client` for one-off commands, or have scripts use the client when `project/target/active.json` points at a live socket and fall back to plain sbt otherwise.
- A long-running `run` (Play `api/run`, `mcp/run`) or a job that needs its own JVM options (`-D…`, `-J-Xmx6g`, `clean coverage`). These are legitimate: the thin client can't pass JVM options to a running server, and coverage or `clean` would disturb the shared server. Report them as expected, not as waste.
- The IDE imported the project the old way (sbt shell / sbt import) instead of over BSP, so it runs its own sbt. Look for an sbt JVM whose parent is the IDE without `-bsp` in its command.

**A git worktree open in its own IDE window** costs a second index and a second sbt server for the same repo. Recommend working in worktrees from a terminal and opening them in the IDE only to review.

**Server without the project environment.** An sbt server started directly by the IDE inherits the IDE's environment, not the project's `.envrc`, so tests sharing it run without project secrets or the right `TMPDIR`. Check `ps eww -p <server pid>` for `DIRENV_FILE`. The fix is a `.bsp/sbt.json` whose `argv` runs a wrapper (`direnv exec . sbt -bsp`). IntelliJ sometimes rewrites `.bsp/sbt.json` back to a raw `java … -bsp` command; check it after imports.

## Memory: other JVMs

**Kotlin compile daemon** (`kotlin-daemon`, parent = IDE). Started when the IDE compiles a Kotlin script, notably MCP `run_inspection_kts` calls (custom inspections such as a Grazie proxy). It stays alive afterwards and grows: ~700 MB after one run, 3 GB after a day and a half has been seen. Correlate its start time with `Kotlin script inspections compiled` / `run_inspection_kts` in the log scan. Safe to kill when idle: the IDE starts a new one on demand. A durable fix is for the tool that runs the script to kill only daemons that weren't running before it started. Stale zero-byte `kotlin-compiler-client-*-is-running` files in `~/Library/Application Support/kotlin/daemon` (one per hour, phase-locked to the daemon's start) are the IDE's client re-registering, not new compiles; they are harmless.

**Gradle daemon:** same story for Gradle projects; `gradle --stop` ends idle ones.

**MCP servers that are JVMs** (`jar:…`): a stdio MCP server written in Java/Scala costs ~130–200 MB per copy, and every session that loads it starts another copy. A stateless one can be given an HTTP mode and run once (LaunchAgent, localhost only), with sessions pointed at it via a local-scope entry (`claude mcp add -s local --transport http <name> http://127.0.0.1:<port>/…`) so team `.mcp.json` files stay unchanged. Cap its heap (`-Xmx256m`) and add `-XX:G1PeriodicGCInterval=60000` so idle heap is returned.

## Memory: MCP servers and Claude sessions

A **Claude Code session** itself is ~200–360 MB. Its **stdio MCP servers run once per session**, so `N procs in M sessions` with M > 1 is duplication by design.

- **Unused servers** are the cheapest win. Check whether a server is ever used before recommending it stay: search the session transcripts (`~/.claude/projects/<project>/**/*.jsonl`) for `"type":"tool_use"` entries whose `name` starts with `mcp__<server>__`. Matches inside tool *definitions* (the tool list a session or subagent loads) are not uses. Note that directory names there start with `-`, so pass them to `ls`/`grep` after `--` or with a `./` prefix.
- **To disable a project's `.mcp.json` server for yourself only:** `"disabledMcpjsonServers": ["name", …]` in `~/.claude/settings.json` (applies in every project) or a project's `.claude/settings.local.json`. A local-scope server added with `claude mcp add` is removed with `claude mcp remove <name> -s local`. Running sessions keep their copies until restarted; kill them if the user agrees (`pgrep -f '<pattern>' | xargs kill`; zsh won't word-split an unquoted `$pids`, and macOS `pgrep` has no `-E`).
- **Browser-driving servers** (chrome-devtools-mcp, safari-mcp, playwright) are stateful (selected tab/page), so they can't be shared between sessions; disable them where unused instead of trying to share them. ~100–200 MB per session each, more with helper processes.
- **Docker-based MCP servers** (`docker run -i … mcp-grafana`) put their memory in the Docker VM, not under the session; check `docker stats`.

## Memory: the IDE, the system, other apps

- **IDE footprint vs heap.** A 4–8 GB footprint with 1–2 GB heap used is normal (metaspace, code cache, native, JCEF). Low heap use against a large `-Xmx` is fine: unused heap isn't committed. Real pressure shows as heap used near max, low-memory warnings or freezes in the log.
- **Each project window** costs index and model memory; closing windows nobody reviews in the IDE is a real saving. The JCEF helper processes (embedded browser, Markdown preview, AI chat panels) can reach several GB.
- **Swap near full** with plenty of free RAM is usually left over from an earlier squeeze; it drains slowly or on reboot. Swap filling *now* together with low free % is current pressure.
- **Spotlight (`mds_stores`, `mdworker`)** is high for a while after a reboot or big checkouts; transient.
- **Browsers** are often the largest consumer on the machine. Worth naming, but outside the IDE's scope; mention once.
- **Docker Desktop:** the VM's size is what Docker reserves for containers; a Mongo container takes about half the VM by default unless `--wiredTigerCacheSizeGB` caps it, and Elasticsearch takes a large heap unless `ES_JAVA_OPTS` sets one.

## Log: real problems

- **`BSP server is not responding` / `Problem executing BSP job` (BspSession), often with SEVERE "Plugin to blame: Scala".** The IDE's BSP client lost its sbt server: the server was killed, hung, or restarted with a new socket. Thousands of repeats (see "Repeating exceptions IntelliJ stopped logging") mean the window kept retrying for hours. Find the project and time window, check whether that checkout's server is alive (`project/target/active.json` → socket exists?), and recommend a BSP Reload in that window, or reopening it. Also see whether something killed sbt servers around the first occurrence.
  A **steady retry every ~20 s for days** is a different case: a BSP session that failed to initialize and was never disposed. Seen once after an experiment that made the server fail its start (a locked `.bsp/sbt.json`): the session began retrying on Nov 7 11:17, a later Reload in the same window connected a *new* session fine, and the orphan kept retrying (~20,000 attempts, "Suppressed … for the 5000th time" in each rotated log) until the IDE was restarted on Nov 12. The log lines don't name the project; find it from the first failure (the `External project [<path>] resolution task started` line just before it). Only an IDE restart clears it; closing and reopening that project window may also work. It costs log noise and a little CPU, not memory, since no JVM is started per retry.
- **`PSI and index do not match` / `Outdated stub in index`.** Index corruption for a file, usually after files change on disk while indexing (branch switches, generated sources). One-offs are harmless; repeats for the same project merit *File → Invalidate Caches* for that project.
- **`java.lang.OutOfMemoryError`, low-memory warnings, UI freezes.** Real IDE pressure. Check heap via `jcmd`, the number of open windows, and the plugins named in nearby errors. Raise `-Xmx` in `idea.vmoptions` only after removing the cause.
- **Indexing passes ≥10 s** clustered at one timestamp across every project: a global event (IDE start, SDK or shared index change). Repeated slow passes for one project: big generated or vendored directories that should be excluded.
- **`io.ktor.server.cio.HttpServer` "Unhandled exception … request-handler"** comes from the IDE's built-in MCP/HTTP server, usually a client disconnecting mid-request. Occasional ones are noise; a burst lines up with a Claude session being killed or restarted.
- **MCP tool traffic.** `MCP tools served by the IDE` shows which IDE tools sessions lean on. Many `run_inspection_kts` calls mean Kotlin daemons (see above). Heavy `get_file_problems` / `search_regex` use is normal.

## Log: known noise

- **`SbtUtil$ - Can't calculate external root project path for project X`**: thousands per day, one per non-sbt project window on every status update. Harmless; report it in one line.
- **`ExternalSystemNotificationReporter - Skipping output for a finished task`**: sbt output arriving after a BSP task ended (compiler and test output). Harmless.
- **`SettingsSyncBridge - Pending events is empty`**: heartbeat; dominates WARN volume in some builds.
- **`MenuCancelledControlFlowException`, `GithubConfusingException`, `EntityDoesNotExistException`**: UI and plugin internals; ignore unless they cluster with a user-visible problem.
- **Launcher stdout** (`SLF4J … no providers`, `IMKCFRunLoopWakeUpReliable`, Toolbox `daemon-client-ws … Ping timeout`): macOS input-method and JetBrains Toolbox chatter. Harmless.
- **The build/JDK/OS banner** after each SEVERE: context lines, already filtered by `log_scan.py`.
