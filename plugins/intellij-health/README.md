# intellij-health

A Claude Code skill that checks how IntelliJ IDEA and the machine it runs on are
doing, for a setup where many Claude Code sessions work alongside the IDE.

It reads IntelliJ's logs (errors and the plugins they blame, BSP and sbt
trouble, freezes, indexing, MCP tool traffic) and the machine's memory use (IDE
heap and footprint, sbt servers and BSP clients per checkout, Kotlin and Gradle
daemons, MCP servers duplicated per session, swap). It then reports what is
wrong and what to do about it, and changes nothing without your permission.

Ask things like "how is IntelliJ doing?", "why is everything slow?", "what is
eating memory?" or "review the IDE log".

## Install

```
/plugin marketplace add WamBamBoozle/AgenticIntelliJ
/plugin install intellij-health@agentic-intellij
```

## Platforms

The log scan reads IntelliJ's logs on macOS (`~/Library/Logs/JetBrains`) and
Linux (`~/.cache/JetBrains`). The memory snapshot is macOS only. Both scripts
need only Python 3's standard library.

Part of [AgenticIntelliJ](https://github.com/WamBamBoozle/AgenticIntelliJ). MIT licensed.
