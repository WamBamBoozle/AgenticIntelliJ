## sbt: share one server per checkout

Memory on this machine is tight, and every plain `sbt` command starts a new
1–2 GB JVM. For one-off commands (compile, test, testOnly, scalafmt, show, …)
use the thin client, which connects to the checkout's running sbt server or
starts one:

    sbt --client "testOnly com.example.FooSpec"

- One server per checkout is shared by IntelliJ (over BSP), every session and
  every terminal in it, so commands from different sessions in the same
  checkout run one after another.
- When you are done with a checkout you started a server in, stop it:
  `sbt --client shutdown`. Don't shut down a server you didn't start.
- Keep using plain `sbt` where a long-running process needs its own JVM and
  terminal, such as a Play `run` or a project script that launches sbt itself.
