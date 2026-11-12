---
name: intellij-health
description: Comprehensive health check of IntelliJ IDEA and the Mac it runs on, for a setup where many Claude Code sessions work alongside the IDE. Evaluates IntelliJ's logs (idea.log errors, plugin blame, BSP/sbt trouble, freezes, indexing, MCP tool traffic) and memory usage (IDE heap and footprint, sbt servers and BSP clients per checkout, Kotlin/Gradle daemons, MCP servers duplicated per Claude session, swap), then reports what is wrong and what to do about it. Use this whenever the user asks how IntelliJ or the machine is doing, why things are slow, what is eating memory, whether a change (BSP, shared sbt servers, killing a daemon, disabling MCP servers) helped, wants the IDE log reviewed, or has just rebooted or restored sessions and wants an assessment, even if they don't say "health check".
---

# IntelliJ health check

Two questions, answered with evidence: **what is IntelliJ's log saying**, and **where is the memory going**. The machine typically runs one IntelliJ with several project windows, a sbt server per Scala checkout shared over BSP, and many Claude Code sessions, each of which starts its own copies of stdio MCP servers. Most memory problems in that setup are duplication (several JVMs or MCP servers doing one job) or leftovers (daemons nobody needs any more), and most log problems are a handful of loud, repeating failures hiding among tens of thousands of harmless warnings.

## Procedure

1. **Collect.** Run both scripts (in parallel; each takes a few seconds):

   ```bash
   python3 <skill-dir>/scripts/memory_snapshot.py          # add --json for machine-readable output
   python3 <skill-dir>/scripts/log_scan.py --rotated 1     # current + previous idea.log
   ```

   `log_scan.py` options: `--since "YYYY-MM-DD HH:MM"` to look only at the current incident or the time since a change; `--rotated N` to go further back; `--log-dir` if the IDE's log isn't found automatically; `--top N` for more rows. Both scripts need only the Python standard library; the snapshot is macOS-only.

2. **Dig into what stands out.** The scripts rank and count; they don't explain. For each serious item, look at the evidence directly before drawing a conclusion:
   - A loud log entry: `grep -n` it in idea.log and read the lines around the first and last occurrence (stack trace, what happened just before). A burst at one moment usually has one cause.
   - A suspicious process: `ps -o ppid=,lstart=,command= -p <pid>` for who started it and when, `lsof -a -p <pid> -d cwd` for its directory, `ps eww -p <pid>` to see whether it got the project's environment (for example `DIRENV_FILE`).
   - A JVM's real heap: `jcmd <pid> GC.heap_info`. A process footprint far above its heap use is normal for the IDE (code cache, metaspace, native, JCEF).
   - Correlate times: a daemon's start time against the log (e.g. a `run_inspection_kts` call) usually tells you what started it.

3. **Interpret** using `references/interpretation.md`. It lists the patterns that have mattered in practice, which ones are noise, and what fixed them. Read it before writing the report; it will save you from reporting the 5,000 harmless `SbtUtil` warnings as a problem, or from missing that one sbt JVM too many is the biggest win on the machine.

4. **Report** (format below). Lead with the verdict, then the few things worth acting on, ranked by payoff.

5. **Act only with permission.** Offer remedies; don't kill processes, edit settings or close windows on your own. Killing a process another session or the IDE owns has side effects the user should choose (a session sees its MCP server fail; a running build dies). When the user agrees, do it, then re-run the relevant script to show the effect. If the project keeps an execution log or changelog convention, record what you changed and the commands you used.

## Measuring honestly

- **Footprint, not RSS.** On macOS, idle processes get compressed or swapped; RSS then understates them badly. `memory_snapshot.py` uses `footprint` (phys_footprint) for JVMs, the IDE, Claude sessions and their children. Its per-app table is RSS and overcounts shared pages, so use it only to rank applications.
- **Free memory after a kill may not move much.** Killing an idle, compressed process mostly frees compressor space and swap, not "free" RAM. Say so instead of claiming a number you didn't see.
- **No baseline, no saving.** If nobody measured before a change, say the saving is structural (e.g. "one sbt JVM per checkout instead of up to three") rather than inventing a figure. Suggest saving the snapshot (`--json`) so the next comparison has one.
- **A snapshot is a moment.** sbt servers start lazily (on the first BSP sync or `sbt --client`), Spotlight re-indexes after a reboot, Docker grows with containers. Note what the timing implies, e.g. "no sbt servers yet; expect ~1.5 GB per checkout once you build".

## Report format

```markdown
## Verdict
One or two sentences: healthy or not, and the single most important thing.

## Memory
- System: RAM, free %, swap used, compressed.
- Table of the biggest consumers (footprint), grouped meaningfully: IDE (heap used / max), sbt servers and BSP clients per checkout, other JVMs, Claude sessions, MCP servers by kind (count × sessions), browsers, Docker.
- Duplicates and leftovers called out explicitly.

## IntelliJ log
- Window covered, IDE restarts.
- Real problems (with counts, time range, likely cause): e.g. BSP server not responding, plugin errors, OOM, freezes.
- Known noise, in one line, so the user knows it was seen and dismissed.
- Agentic traffic: MCP tool calls served, Kotlin script compiles.

## Recommendations
Numbered, biggest payoff first. Each: what, how much it saves or fixes, the exact command or setting, and any side effect. Ask which to do.
```

Keep it tight. Tables for numbers, a sentence of interpretation each, no restating raw script output the user can't act on.
