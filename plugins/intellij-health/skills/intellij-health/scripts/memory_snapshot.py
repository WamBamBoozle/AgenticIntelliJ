#!/usr/bin/env python3
"""memory_snapshot: what is using memory on a Mac running IntelliJ and Claude Code sessions.

Prints a report (or JSON with --json) covering:
  - system: RAM, free percentage, swap, compressed memory
  - IntelliJ: process footprint, live heap (via jcmd), open project windows
  - JVMs: every java process, classified (sbt server, BSP client, Kotlin/Gradle daemon, jar),
    with its working directory, age and footprint; duplicate sbt JVMs per checkout are flagged
  - Claude sessions: one row per session, with the MCP servers and other children it started
  - MCP servers aggregated by kind across sessions (stdio servers are started once per session)
  - apps grouped by .app bundle (RSS, which overcounts shared pages; good for ranking only)
  - Docker containers, if docker is available

macOS only (uses footprint, memory_pressure, vm_stat, lsof, osascript). Standard library only.
Footprint ("phys_footprint") counts compressed and swapped pages, so it is the honest per-process
number on macOS; RSS is not.
"""
import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")


def run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def tilde(path):
    return path.replace(HOME, "~", 1) if path and path.startswith(HOME) else path


# ---------------------------------------------------------------- system

def system_info():
    info = {}
    mem = run(["sysctl", "-n", "hw.memsize"]).strip()
    info["ram_gb"] = round(int(mem) / 2**30, 1) if mem.isdigit() else None
    m = re.search(r"free percentage:\s*(\d+)%", run(["memory_pressure"]))
    info["free_percent"] = int(m.group(1)) if m else None
    sw = run(["sysctl", "vm.swapusage"])
    t = re.search(r"total = ([\d.]+)M", sw)
    u = re.search(r"used = ([\d.]+)M", sw)
    info["swap_total_mb"] = float(t.group(1)) if t else None
    info["swap_used_mb"] = float(u.group(1)) if u else None
    vm = run(["vm_stat"])
    page = re.search(r"page size of (\d+) bytes", vm)
    page = int(page.group(1)) if page else 16384
    for key, label in (("Pages active", "active_gb"), ("Pages wired down", "wired_gb"),
                       ("Pages occupied by compressor", "compressed_gb")):
        m = re.search(re.escape(key) + r":\s+(\d+)", vm)
        info[label] = round(int(m.group(1)) * page / 2**30, 1) if m else None
    up = run(["uptime"]).strip()
    info["uptime"] = up.split(",")[0].split("up", 1)[-1].strip() if "up" in up else up
    return info


# ---------------------------------------------------------------- processes

class Proc:
    __slots__ = ("pid", "ppid", "rss_mb", "etime", "cmd", "cwd", "footprint_mb")

    def __init__(self, pid, ppid, rss_kb, etime, cmd):
        self.pid, self.ppid, self.etime, self.cmd = pid, ppid, etime, cmd
        self.rss_mb = rss_kb / 1024
        self.cwd = None
        self.footprint_mb = None


def processes():
    out = run(["ps", "-axo", "pid=,ppid=,rss=,etime=,command="])
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid, ppid, rss, etime, cmd = parts
        procs[int(pid)] = Proc(int(pid), int(ppid), int(rss), etime, cmd)
    return procs


def fill_cwd(procs, pids):
    pids = [p for p in pids if p in procs]
    if not pids:
        return
    out = run(["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(map(str, pids))])
    current = None
    for line in out.splitlines():
        if line.startswith("p"):
            current = int(line[1:])
        elif line.startswith("n") and current in procs:
            procs[current].cwd = line[1:]


def fill_footprint(procs, pids):
    for pid in pids:
        if pid not in procs or procs[pid].footprint_mb is not None:
            continue
        m = re.search(r"phys_footprint:\s+([\d.]+)\s+(KB|MB|GB)", run(["footprint", "-p", str(pid)], 20))
        if m:
            v = float(m.group(1))
            procs[pid].footprint_mb = v / 1024 if m.group(2) == "KB" else v * 1024 if m.group(2) == "GB" else v


def mb(p):
    """Footprint when measured, else RSS."""
    return p.footprint_mb if p.footprint_mb is not None else p.rss_mb


IDE_RE = re.compile(r"/Contents/MacOS/(idea|pycharm|webstorm|goland|clion|rider|rubymine|phpstorm)(\s|$)")
CLAUDE_RE = re.compile(r"^(\S*/)?claude(\s|$)")
JAVA_RE = re.compile(r"^(\S*/)?java(\s|$)")


def classify_java(cmd):
    if "KotlinCompileDaemon" in cmd or "kotlin-daemon" in cmd:
        return "kotlin-daemon"
    if "GradleDaemon" in cmd:
        return "gradle-daemon"
    if "sbt-launch" in cmd or "xsbt.boot" in cmd or "-Dsbt.script" in cmd:
        if re.search(r"\s-bsp(\s|$)", cmd):
            return "sbt-bsp-client"
        if re.search(r"\s--client(\s|$)", cmd):
            return "sbt-client"
        if re.search(r"\b\w+/run\b|-Dhttp\.port=", cmd):
            return "sbt-run"
        return "sbt"
    if "org.jetbrains.jps" in cmd or "jps-builders" in cmd:
        return "intellij-build-process"
    jar = re.search(r"-jar\s+(.+?\.jar)(\s|$)", cmd) or re.search(r"-jar\s+(\S+)", cmd)
    if jar:
        return "jar:" + os.path.basename(jar.group(1))
    main = re.findall(r"\s([a-z][\w.]+\.[A-Z]\w+)(\s|$)", cmd)
    return "java:" + (main[-1][0] if main else "?")


MCP_HINTS = [
    (re.compile(r"npm exec (@?[\w./-]+?)(@[\w.^~-]+)?(\s|$)"), 1),
    (re.compile(r"npx (?:-y )?(@?[\w./-]+?)(@[\w.^~-]+)?(\s|$)"), 1),
    (re.compile(r"/_npx/\w+/node_modules/(?:\.bin/)?(@?[\w.-]+(?:/[\w.-]+)?)"), 1),
    (re.compile(r"uvx (?:--from \S+ )?([\w.-]+)"), 1),
    (re.compile(r"-jar\s+(.+?\.jar)(\s|$)"), 1),
    (re.compile(r"docker run .*?\s([\w./-]+/[\w.-]+)(:\S+)?(\s+--|\s*$)"), 1),
]


def child_label(cmd):
    for rx, g in MCP_HINTS:
        m = rx.search(cmd)
        if m:
            label = os.path.basename(m.group(g)) if "-jar" in rx.pattern else m.group(g)
            return re.sub(r"\.bin/", "", label)
    words = cmd.split()
    first = os.path.basename(words[0])
    # An interpreter running a tool: name the tool, not the interpreter.
    if re.match(r"(python[\d.]*|node|ruby|bash|sh|zsh)$", first):
        for w in words[1:]:
            if not w.startswith("-"):
                return os.path.basename(w)
    return first


def session_children(procs, claude_pids):
    """Map every descendant of a Claude session (except its Bash tool shells) to that session."""
    owner = {}
    for pid, p in procs.items():
        if pid in claude_pids:
            continue
        cur, hops = p.ppid, 0
        while cur in procs and hops < 30:
            if cur in claude_pids:
                owner[pid] = cur
                break
            cur, hops = procs[cur].ppid, hops + 1
    # Drop Bash tool command trees: they run under a zsh/bash -c "source …shell-snapshots…" shell.
    tool_roots = {pid for pid in owner if "shell-snapshots" in procs[pid].cmd}

    def under_tool(pid):
        cur, hops = pid, 0
        while cur in procs and hops < 30:
            if cur in tool_roots:
                return True
            if cur in claude_pids:
                return False
            cur, hops = procs[cur].ppid, hops + 1
        return False

    return {pid: s for pid, s in owner.items() if not under_tool(pid)}


def app_groups(procs):
    groups = collections.Counter()
    for p in procs.values():
        m = re.search(r"/([^/]+)\.app/", p.cmd)
        name = m.group(1) if m else os.path.basename(p.cmd.split()[0])
        if CLAUDE_RE.match(p.cmd):
            name = "Claude Code sessions"
        groups[name] += p.rss_mb
    return groups


# ---------------------------------------------------------------- IntelliJ specifics

def ide_heap(pid):
    if not shutil.which("jcmd"):
        return None
    out = run(["jcmd", str(pid), "GC.heap_info"], 30)
    m = re.search(r"total reserved (\d+)K, committed (\d+)K, used (\d+)K", out)
    if not m:
        return None
    reserved, committed, used = (int(x) / 1024 for x in m.groups())
    return {"max_mb": round(reserved), "committed_mb": round(committed), "used_mb": round(used)}


def ide_windows(process_name="idea"):
    out = run(["osascript", "-e",
               f'tell application "System Events" to get name of every window of process "{process_name}"'], 20)
    return [w.strip() for w in out.strip().split(", ") if w.strip()] if out.strip() else []


def docker_containers():
    if not shutil.which("docker"):
        return None
    out = run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], 25)
    rows = []
    for line in out.splitlines():
        try:
            d = json.loads(line)
            rows.append({"name": d.get("Name"), "mem": d.get("MemUsage"), "cpu": d.get("CPUPerc")})
        except json.JSONDecodeError:
            pass
    return rows


# ---------------------------------------------------------------- main

def snapshot():
    procs = processes()
    claude = {pid for pid, p in procs.items() if CLAUDE_RE.match(p.cmd)}
    ides = [pid for pid, p in procs.items() if IDE_RE.search(p.cmd)]
    javas = [pid for pid, p in procs.items() if JAVA_RE.match(p.cmd)]
    children = session_children(procs, claude)

    fill_cwd(procs, list(claude) + javas)
    fill_footprint(procs, ides + javas + list(claude) + list(children))

    data = {"system": system_info()}

    data["ides"] = []
    for pid in ides:
        p = procs[pid]
        name = re.search(r"/Contents/MacOS/(\w+)", p.cmd).group(1)
        data["ides"].append({
            "pid": pid, "age": p.etime, "footprint_mb": round(mb(p)),
            "heap": ide_heap(pid), "windows": ide_windows(name),
        })

    data["jvms"] = []
    for pid in sorted(javas, key=lambda x: -mb(procs[x])):
        p = procs[pid]
        kind = classify_java(p.cmd)
        parent = procs.get(p.ppid)
        parent_kind = ("IDE" if parent and IDE_RE.search(parent.cmd)
                       else "Claude session" if p.ppid in claude
                       else "launchd" if p.ppid == 1 else os.path.basename(parent.cmd.split()[0]) if parent else "?")
        xmx = re.findall(r"-Xmx(\d+[gGmM])", p.cmd)
        data["jvms"].append({
            "pid": pid, "kind": kind, "cwd": tilde(p.cwd), "age": p.etime,
            "footprint_mb": round(mb(p)), "xmx": xmx[-1] if xmx else None, "parent": parent_kind,
        })

    per_dir = collections.defaultdict(list)
    for j in data["jvms"]:
        if j["kind"] in ("sbt", "sbt-run"):
            per_dir[j["cwd"]].append(j["pid"])
    data["duplicate_sbt"] = {d: pids for d, pids in per_dir.items() if len(pids) > 1}

    data["sessions"] = []
    by_session = collections.defaultdict(list)
    for pid, s in children.items():
        by_session[s].append(pid)
    for s in sorted(claude, key=lambda x: tilde(procs[x].cwd or "")):
        p = procs[s]
        name = re.search(r"(?:-n|--name)\s+(\S+)", p.cmd)
        kids = collections.Counter()
        for c in by_session.get(s, []):
            kids[child_label(procs[c].cmd)] += mb(procs[c])
        data["sessions"].append({
            "pid": s, "name": name.group(1) if name else None, "cwd": tilde(p.cwd), "age": p.etime,
            "footprint_mb": round(mb(p)),
            "children_mb": {k: round(v) for k, v in kids.most_common()},
        })

    agg = collections.defaultdict(lambda: {"mb": 0.0, "sessions": set(), "procs": 0})
    for pid, s in children.items():
        label = child_label(procs[pid].cmd)
        agg[label]["mb"] += mb(procs[pid])
        agg[label]["sessions"].add(s)
        agg[label]["procs"] += 1
    data["session_children"] = sorted(
        ({"label": k, "mb": round(v["mb"]), "sessions": len(v["sessions"]), "procs": v["procs"]}
         for k, v in agg.items()), key=lambda r: -r["mb"])

    data["apps_rss_mb"] = {k: round(v) for k, v in app_groups(procs).most_common(15)}
    data["docker"] = docker_containers()
    return data


def report(d):
    s = d["system"]
    out = ["== System"]
    swap = (f"{s['swap_used_mb']:.0f} of {s['swap_total_mb']:.0f} MB"
            if s["swap_total_mb"] is not None else "?")
    out.append(f"RAM {s['ram_gb']} GB · free {s['free_percent']}% · swap used {swap} · "
               f"compressed {s['compressed_gb']} GB · wired {s['wired_gb']} GB · active {s['active_gb']} GB · up {s['uptime']}")

    out.append("\n== IDE")
    for i in d["ides"] or []:
        h = i["heap"]
        heap = (f"heap used {h['used_mb']} MB, committed {h['committed_mb']} MB, max {h['max_mb']} MB"
                if h else "heap n/a (no jcmd or attach refused)")
        out.append(f"pid {i['pid']} · footprint {i['footprint_mb']} MB · {heap} · up {i['age']}")
        out.append(f"  {len(i['windows'])} windows: " + "; ".join(i["windows"]))
    if not d["ides"]:
        out.append("no IntelliJ-family IDE running")

    out.append("\n== JVMs (footprint)")
    for j in d["jvms"]:
        out.append(f"{j['pid']:>6} {j['footprint_mb']:>6} MB  {j['kind']:<24} xmx={j['xmx'] or '-':<6} "
                   f"parent={j['parent']:<14} up {j['age']:<12} {j['cwd'] or ''}")
    if d["duplicate_sbt"]:
        out.append("!! more than one sbt JVM in: " +
                   "; ".join(f"{k} (pids {', '.join(map(str, v))})" for k, v in d["duplicate_sbt"].items()))

    out.append("\n== Claude sessions")
    for c in d["sessions"]:
        kids = ", ".join(f"{k} {v}" for k, v in c["children_mb"].items()) or "-"
        out.append(f"{c['pid']:>6} {c['footprint_mb']:>5} MB  {c['name'] or '-':<22} {c['cwd'] or ''}")
        out.append(f"         children (MB): {kids}")

    out.append("\n== Session children by kind (a stdio MCP server runs once per session)")
    for r in d["session_children"]:
        out.append(f"{r['mb']:>6} MB  {r['label']:<40} {r['procs']} procs in {r['sessions']} sessions")

    out.append("\n== Apps by RSS (overcounts shared pages; use for ranking only)")
    for k, v in d["apps_rss_mb"].items():
        out.append(f"{v:>7} MB  {k}")

    if d["docker"] is not None:
        out.append("\n== Docker containers")
        out += [f"{r['name']}: {r['mem']} (cpu {r['cpu']})" for r in d["docker"]] or ["none running"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the text report")
    args = ap.parse_args()
    if sys.platform != "darwin":
        sys.exit("memory_snapshot: macOS only (footprint, memory_pressure, vm_stat)")
    d = snapshot()
    print(json.dumps(d, indent=2) if args.json else report(d))


if __name__ == "__main__":
    main()
