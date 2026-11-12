# AgenticIntelliJ shell setup, for bash or zsh. Source it from ~/.bashrc or
# ~/.zshrc, after anything that puts `claude` and `direnv` on PATH:
#
#   source ~/src/AgenticIntelliJ/shell/agentic-intellij.sh
#
# It puts this repository's bin/ on PATH, sets JVM options for sbt, and runs any
# session `load-project` or `intellij-sessions restore` queued for the directory
# an IntelliJ terminal opens in.

# This repository's bin/, found from this file's own location. zsh's form is
# behind eval because bash can't parse it.
if [ -n "${ZSH_VERSION:-}" ]; then
  eval '__ai_self=${(%):-%x}'
else
  __ai_self=${BASH_SOURCE[0]}
fi
__ai_bin="$(cd "$(dirname "$__ai_self")/../bin" && pwd -P)"
case ":$PATH:" in
  *":$__ai_bin:"*) ;;
  *) PATH="$__ai_bin:$PATH" ;;
esac
unset __ai_self __ai_bin

# JVM options for every sbt (sdkman's and nix's launchers both read SBT_OPTS).
# Plain -XX: flags, not -J-XX:, because older launchers pass SBT_OPTS to java unchanged.
#
# -XX:+IgnoreUnrecognizedVMOptions: checkouts build on different JDKs, and without
#   this a JDK that doesn't know one of the flags below refuses to start at all.
# -XX:+UseCompactObjectHeaders: Java 25 can shrink every object's header from
#   12 to 8 bytes, and sbt and the Scala compiler allocate enough small objects
#   that this cuts their heap noticeably; older JDKs skip it (see above).
# -XX:G1PeriodicGCInterval=60000: an sbt server sits idle most of the day holding
#   the heap its last compile grew to; a collection every idle minute hands that
#   unused memory back to the OS.
export SBT_OPTS="-XX:+IgnoreUnrecognizedVMOptions -XX:+UseCompactObjectHeaders -XX:G1PeriodicGCInterval=60000"

# Run a session queued by `load-project` or `intellij-sessions` when a fresh
# IntelliJ terminal opens here. The queue file, named by the sha1 of this
# directory's real path, holds one command per line, since several sessions can
# share a directory; each new terminal takes the first line and removes it
# before running it. The lock keeps two tabs that open at once from taking the
# same line (after 5s a stale lock is ignored).
if [ "${TERMINAL_EMULATOR:-}" = "JetBrains-JediTerm" ]; then
  __lp_pend="$HOME/.cache/load-project/pending/$(printf '%s' "$(pwd -P)" | shasum | cut -d' ' -f1)"
  if [ -s "$__lp_pend" ]; then
    __lp_try=0
    while ! mkdir "$__lp_pend.lock" 2>/dev/null && [ $((__lp_try += 1)) -le 50 ]; do sleep 0.1; done
    __lp_cmd=""
    if [ -s "$__lp_pend" ]; then
      __lp_cmd=$(head -n 1 "$__lp_pend")
      __lp_rest=$(tail -n +2 "$__lp_pend")
      if [ -n "$__lp_rest" ]; then
        printf '%s\n' "$__lp_rest" > "$__lp_pend"
      else
        rm -f "$__lp_pend"
      fi
    fi
    rmdir "$__lp_pend.lock" 2>/dev/null
    unset __lp_try __lp_rest
    if [ -n "$__lp_cmd" ]; then
      # A nested session inherits the parent's transcript unless this is cleared.
      unset CLAUDE_CODE_CHILD_SESSION
      printf '\033[32mload-project\033[0m: %s\n' "$__lp_cmd"
      unset __lp_pend
      eval "$__lp_cmd"
    fi
    unset __lp_cmd
  fi
  unset __lp_pend
fi
