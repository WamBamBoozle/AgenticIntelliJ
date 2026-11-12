// Keep IntelliJ's BSP connection file pointed at sbt-bsp (this repo's bin/).
// Install by linking it into sbt's global directory:
//   ln -s "$PWD/sbt/global.sbt" ~/.sbt/1.0/global.sbt
//
// sbt 1.x rewrites <build>/.bsp/sbt.json every time a server starts, to run
// java directly. A server IntelliJ then starts from that file lacks the
// project's direnv environment (secrets, per-checkout TMPDIR), and so does every
// `sbt --client` run that shares it. In builds sbt-bsp-setup has prepared, it
// leaves .bsp/.use-sbt-bsp holding its own path; wait for sbt's rewrite and run
// that sbt-bsp-setup again. Elsewhere this does nothing.
Global / onLoad := (Global / onLoad).value andThen { state =>
  val build = state.baseDir
  val marker = new File(build, ".bsp/.use-sbt-bsp")
  val conn = new File(build, ".bsp/sbt.json")
  def ours = conn.exists && IO.read(conn).contains("/bin/sbt-bsp\"")
  val setup = if (marker.exists) Some(new File(IO.read(marker).trim)).filter(_.canExecute) else None
  setup.foreach { setup =>
    val t = new Thread(() => {
      // The server writes the file shortly after the build loads; look for a
      // minute, since a slow load can delay it.
      var tries = 0
      while (tries < 30) {
        Thread.sleep(2000)
        if (conn.exists && !ours) {
          scala.sys.process.Process(Seq(setup.getPath, build.getPath)).!
          tries = 30
        }
        tries += 1
      }
    }, "sbt-bsp-guard")
    t.setDaemon(true)
    t.start()
  }
  state
}
