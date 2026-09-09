"""18-G pipe H1: clean-env operator workflow."""
import shutil
import subprocess
import time


def clean_env_workflow(mod, jar_path, port):
    mod["CLEANDIR"].mkdir(parents=True, exist_ok=True)
    clean_jar = mod["CLEANDIR"] / "app.jar"
    shutil.copyfile(jar_path, clean_jar)
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin",
           "JAVA_HOME": "/opt/homebrew/Cellar/openjdk/26.0.2.1/libexec/openjdk.jdk/Contents/Home"}
    java_bin = mod["java_bin"]()
    log_path = mod["CLEANDIR"] / "clean_run.log"
    with open(log_path, "w") as logf:
        proc = subprocess.Popen(
            [java_bin, "-Dserver.port=%d" % port, "-Dspring.main.banner-mode=off",
             "-jar", str(clean_jar)],
            stdout=logf, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    deadline = time.time() + 45
    up = False
    while time.time() < deadline:
        time.sleep(1.0)
        if proc.poll() is not None:
            break
        try:
            st, body = mod["http_get"](port, "/api/health", timeout=2.0)
            if st == 200 and body.get("status") == "UP":
                up = True
                break
        except Exception:
            continue
    assert up, "clean-env app failed to start; see %s" % log_path
    checks = [{"step": "install+start", "status": "PASSED"}]
    for name, path in [("health", "/api/health"),
                       ("actuator", "/actuator/health"),
                       ("components", "/api/subsystem/components")]:
        st, body = mod["http_get"](port, path)
        ok = st == 200 and (body.get("status") in ("UP", "SUCCESS")
                            or "totalComponents" in body or "returnCode" in body)
        checks.append({"step": name, "status": "PASSED" if ok else "FAILED", "http": st})
        assert ok, "clean-env step failed: %s -> %s" % (name, st)
    for name, path in [("date-op", "/api/subsystem/evaluate-date?date=2026-09-06"),
                       ("batch-op", "/api/subsystem/execute/Bnkstmt"),
                       ("transfer-op", "/api/execute/Bnk1tfn/execute")]:
        st, body = mod["http_get"](port, path)
        ok = st == 200 and ("returnCode" in body or "status" in body)
        checks.append({"step": name, "status": "PASSED" if ok else "FAILED", "http": st})
        assert ok, "clean-env step failed: %s -> %s" % (name, st)
    before = mod["http_get"](port, "/api/subsystem/components")[1]["totalComponents"]
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    return {"checks": checks, "log": str(log_path), "components": before,
            "proc_done": True}
