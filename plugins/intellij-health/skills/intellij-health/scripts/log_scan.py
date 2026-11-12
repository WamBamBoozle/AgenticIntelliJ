#!/usr/bin/env python3
"""log_scan: summarize IntelliJ's idea.log so a reader can see what went wrong and when.

Reads the IDE's own log (idea.log, plus rotated idea.N.log files with --rotated) and reports:
  - time span, IDE starts, entries per level
  - the loudest WARN / ERROR / SEVERE sources, with a sample message and first/last time
  - "Plugin to blame" attributions and the exception types named in stack traces
  - performance: UI freezes, low-memory warnings, OutOfMemoryError, slow indexing passes
  - projects opened and closed, BSP/sbt connection trouble
  - MCP tool calls the IDE served (from Claude sessions using IntelliJ's MCP server)

It also prints the tail of the launcher's stdout log if one exists (default ~/logs/idea_backup.log,
the previous run as saved by this repo's bin/intellij). Standard library only.
"""
import argparse
import collections
import glob
import os
import re
import sys

HOME = os.path.expanduser("~")
# IntelliJ follows each SEVERE with these as separate log lines; they are context, not errors.
BANNER = re.compile(r"^(IntelliJ IDEA \S+\s+Build|JDK: |OS: |Last Action: |Plugin to blame: )")
LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ \[\s*\d+\]\s+(\w+) - (\S+) - (.*)$")


def default_log_dir():
    roots = [os.path.join(HOME, "Library/Logs/JetBrains"), os.path.join(HOME, ".cache/JetBrains")]
    cands = []
    for r in roots:
        for d in glob.glob(os.path.join(r, "*")):
            log = d if os.path.exists(os.path.join(d, "idea.log")) else os.path.join(d, "log")
            if os.path.exists(os.path.join(log, "idea.log")):
                cands.append(log)
    return max(cands, key=lambda d: os.path.getmtime(os.path.join(d, "idea.log"))) if cands else None


def norm(msg):
    """Collapse numbers, paths and ids so repeats of one problem group together."""
    msg = re.sub(r"(/[\w.@~+-]+)+", "<path>", msg)
    msg = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", msg)
    msg = re.sub(r"\b\d+(st|nd|rd|th)\b", "Nth", msg)
    msg = re.sub(r"\d+", "N", msg)
    return msg[:160]


def entries(files, since):
    """Yield (time, level, logger, message, continuation_lines), oldest file first."""
    for f in files:
        cur = None
        with open(f, errors="replace") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                m = LINE.match(line)
                if m:
                    if cur and (not since or cur[0] >= since):
                        yield cur
                    cur = (m.group(1), m.group(2), m.group(3), m.group(4), [])
                elif cur is not None:
                    cur[4].append(line)
        if cur and (not since or cur[0] >= since):
            yield cur


def scan(files, since):
    r = {
        "first": None, "last": None, "levels": collections.Counter(), "starts": [],
        "noisy": {lvl: collections.Counter() for lvl in ("WARN", "ERROR", "SEVERE")},
        "sample": {}, "span": {}, "blame": collections.Counter(), "exceptions": collections.Counter(),
        "freezes": [], "lowmem": [], "oom": [], "slow_index": [], "opened": [], "closed": [],
        "bsp": collections.Counter(), "suppressed": {}, "tools": collections.Counter(), "kts_compiles": [],
    }
    for t, lvl, logger, msg, cont in entries(files, since):
        r["first"] = r["first"] or t
        r["last"] = t
        r["levels"][lvl] += 1
        if "IDE STARTED" in msg:
            r["starts"].append(t)
        if lvl in r["noisy"] and not BANNER.match(msg):
            key = (logger, norm(msg))
            r["noisy"][lvl][key] += 1
            r["sample"].setdefault(key, msg[:240])
            a, _ = r["span"].get(key, (t, t))
            r["span"][key] = (a, t)
        b = re.search(r"Plugin to blame: (.+?)( version: (\S+))?$", msg)
        if b:
            r["blame"][b.group(1).strip()] += 1
        for c in [msg] + cont:
            e = re.match(r"\s*(?:Caused by: )?((?:[a-z]\w*\.)+[A-Z]\w*(?:Exception|Error))\b", c)
            if e:
                r["exceptions"][e.group(1)] += 1
        if re.search(r"UI was frozen|freeze.*\d+\s*ms|Freeze detected", msg, re.I):
            r["freezes"].append((t, msg[:200]))
        if re.search(r"LowMemoryWatcher|low memory|memory is low", msg, re.I):
            r["lowmem"].append((t, msg[:200]))
        if re.search(r"java\.lang\.OutOfMemoryError", msg) or any("java.lang.OutOfMemoryError" in c for c in cont[:3]):
            r["oom"].append((t, msg[:200]))
        ix = re.search(r"Finished for (.+?)\. .*took (\d+)ms; general responsiveness: (\w+); EDT responsiveness: (\w+)", msg)
        if ix and (int(ix.group(2)) >= 10000 or ix.group(3) != "ok" or ix.group(4) != "ok"):
            r["slow_index"].append((t, ix.group(1), int(ix.group(2)), ix.group(3), ix.group(4)))
        op = re.search(r"Opening (?:existing )?project (?:with \.idea )?at (\S+)", msg)
        if op:
            r["opened"].append((t, op.group(1)))
        cl = re.search(r"Project (.+?) is removed from the list of initializing and open projects", msg)
        if cl:
            r["closed"].append((t, cl.group(1)))
        if (re.search(r"bsp", logger, re.I) or "BSP" in msg) and lvl in ("WARN", "ERROR", "SEVERE") and not BANNER.match(msg):
            r["bsp"][norm(msg)] += 1
        sup = re.search(r"Suppressed a frequent exception logged for the (\d+)\w* time: (.*)", msg)
        if sup:
            k = sup.group(2)[:160]
            r["suppressed"][k] = max(r["suppressed"].get(k, 0), int(sup.group(1)))
        tool = re.search(r'Got Tool: "([\w-]+)"', msg)
        if tool:
            r["tools"][tool.group(1)] += 1
        if "KtsInspectionsManager - Compiling" in f"{logger} - {msg}" or (logger.endswith("KtsInspectionsManager") and msg.startswith("Compiling")):
            r["kts_compiles"].append(t)
    return r


def report(r, files, top, stdout_log):
    out = ["== Scope"]
    out.append("files: " + ", ".join(files))
    out.append(f"span: {r['first']} → {r['last']}   IDE starts: {len(r['starts'])}"
               + (f" (last {r['starts'][-1]})" if r["starts"] else ""))
    out.append("entries: " + ", ".join(f"{k} {v}" for k, v in r["levels"].most_common()))

    for lvl in ("SEVERE", "ERROR", "WARN"):
        c = r["noisy"][lvl]
        if not c:
            continue
        out.append(f"\n== Top {lvl} sources ({sum(c.values())} total)")
        by_logger = collections.Counter()
        for (logger, _), n in c.items():
            by_logger[logger] += n
        out.append("by logger: " + ", ".join(f"{lg} {n}" for lg, n in by_logger.most_common(top)))
        for (logger, _), n in c.most_common(top):
            a, b = r["span"][(logger, _)]
            out.append(f"{n:>6}× {logger}  [{a} → {b}]")
            out.append(f"        {r['sample'][(logger, _)]}")

    if r["blame"]:
        out.append("\n== Plugin to blame")
        out += [f"{n:>6}× {p}" for p, n in r["blame"].most_common(top)]
    if r["exceptions"]:
        out.append("\n== Exception types in messages and stack traces")
        out += [f"{n:>6}× {e}" for e, n in r["exceptions"].most_common(top)]

    out.append("\n== Performance")
    out.append(f"UI freezes: {len(r['freezes'])}   low-memory warnings: {len(r['lowmem'])}   OutOfMemoryError: {len(r['oom'])}")
    for t, m in (r["freezes"] + r["lowmem"] + r["oom"])[-top:]:
        out.append(f"  {t}  {m}")
    out.append(f"indexing passes ≥10 s or not responsive: {len(r['slow_index'])}")
    for t, proj, ms, g, e in sorted(r["slow_index"], key=lambda x: -x[2])[:top]:
        out.append(f"  {t}  {proj}: {ms / 1000:.1f} s (general {g}, EDT {e})")

    out.append("\n== Projects")
    out.append(f"opened {len(r['opened'])}, closed {len(r['closed'])}")
    for t, p in r["opened"][-top:]:
        out.append(f"  open  {t}  {p.replace(HOME, '~')}")
    for t, p in r["closed"][-top:]:
        out.append(f"  close {t}  {p}")

    if r["bsp"]:
        out.append("\n== BSP warnings and errors")
        out += [f"{n:>6}× {m}" for m, n in r["bsp"].most_common(top)]

    if r["suppressed"]:
        out.append("\n== Repeating exceptions IntelliJ stopped logging (highest occurrence count reached)")
        out += [f"{n:>6}× {m}" for m, n in sorted(r["suppressed"].items(), key=lambda x: -x[1])[:top]]

    if r["tools"]:
        out.append(f"\n== MCP tools served by the IDE ({sum(r['tools'].values())} calls)")
        out.append("  " + ", ".join(f"{k} {v}" for k, v in r["tools"].most_common()))
    if r["kts_compiles"]:
        out.append(f"Kotlin script inspections compiled: {len(r['kts_compiles'])} (each can start a Kotlin compile daemon); "
                   f"last {r['kts_compiles'][-1]}")

    if stdout_log and os.path.exists(stdout_log):
        lines = [l.rstrip() for l in open(stdout_log, errors="replace") if l.strip()]
        stamp = re.compile(r"^\d{4}-\d\d-\d\d[ T][\d:.,]+\s+")
        distinct = list(dict.fromkeys(norm(stamp.sub("", l)) for l in lines if not l.startswith(("\tat ", "	at "))))
        out.append(f"\n== Launcher stdout: {stdout_log.replace(HOME, '~')} ({len(lines)} lines, {len(distinct)} distinct)")
        out += ["  " + d for d in distinct[-top:]]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", help="directory holding idea.log (default: the most recently written JetBrains log dir)")
    ap.add_argument("--rotated", type=int, default=0, metavar="N", help="also read idea.1.log … idea.N.log")
    ap.add_argument("--since", help='only entries at or after this time, e.g. "2026-11-12 04:00"')
    ap.add_argument("--top", type=int, default=8, help="rows per section (default 8)")
    ap.add_argument("--stdout-log", default=os.path.join(HOME, "logs/idea_backup.log"),
                    help="launcher stdout log to summarize ('' to skip)")
    args = ap.parse_args()

    log_dir = args.log_dir or default_log_dir()
    if not log_dir:
        sys.exit("log_scan: no idea.log found under ~/Library/Logs/JetBrains or ~/.cache/JetBrains; pass --log-dir")
    files = [os.path.join(log_dir, f"idea.{i}.log") for i in range(args.rotated, 0, -1)]
    files = [f for f in files if os.path.exists(f)] + [os.path.join(log_dir, "idea.log")]
    since = args.since.replace("T", " ") if args.since else None
    print(report(scan(files, since), [f.replace(HOME, "~") for f in files], args.top, args.stdout_log))


if __name__ == "__main__":
    main()
