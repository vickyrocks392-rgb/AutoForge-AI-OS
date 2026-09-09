"""18-G pipe E: live runtime oracle against the REAL generated app."""
import time
import urllib.error
import urllib.request


def pipe_runtime(mod, pid, stages, http_port, plan, mvn):
    t0 = time.perf_counter()
    java = mod["java_bin"]()
    runner = mod["Runner"](jar_path=mvn.fat_jar_path, java_bin=java,
                           port=http_port, startup_timeout_s=40.0)
    rt = runner.start()
    assert rt.started and rt.health_status == "UP"
    behavior = []

    def record(tid, rule, passed, **kw):
        rec = {"test_id": tid, "rule": rule,
               "status": "PASSED" if passed else "FAILED"}
        rec.update(kw)
        behavior.append(rec)
        assert passed, tid + " FAILED: " + str(rec)

    st, comp = mod["http_get"](http_port, "/api/subsystem/components")
    record("BEH_01_REGISTRY", "registry completeness",
           st == 200 and comp.get("totalComponents", 0) == len(plan.target_components),
           total=comp.get("totalComponents"), planned=len(plan.target_components))
    st, dated = mod["http_get"](http_port, "/api/subsystem/evaluate-date?date=2026-09-06")
    record("BEH_02_DATE_HAPPY", "date happy path",
           st == 200 and dated.get("returnCode") == 0
           and dated.get("formattedDate") == "20260906", observed=dated)
    st, badd = mod["http_get"](http_port, "/api/subsystem/evaluate-date?date=BAD-DATE")
    record("BEH_03_DATE_INVALID", "date invalid rejection",
           st == 200 and badd.get("returnCode") == 4 and badd.get("valid") is False,
           observed=badd)
    st, fs00 = mod["http_get"](http_port, "/api/subsystem/evaluate-status?status=00")
    record("BEH_04_STATUS_OK", "status 00 branch",
           st == 200 and fs00.get("returnCode") == 0, observed=fs00)
    st, fs99 = mod["http_get"](http_port, "/api/subsystem/evaluate-status?status=99")
    record("BEH_05_STATUS_ERR", "status error branch",
           st == 200 and fs99.get("returnCode") != 0, observed=fs99)
    batch_names = [getattr(f, "job_name", "") for f in plan.execution_flows] if hasattr(plan, "execution_flows") else []
    job_entry = None
    for cand in comp.get("components", []):
        up = str(cand).upper()
        if "BNKSTMT" in up or "ORCHESTRATION" in up or "JOB" in up:
            job_entry = str(cand)
            break
    if job_entry is None:
        for cand in comp.get("components", []):
            up = str(cand).upper()
            if up.endswith("ORCHESTRATION") or up.endswith("JOB"):
                job_entry = str(cand)
                break
    assert job_entry, "no batch orchestrator component registered: %s" % batch_names
    st, batch = mod["http_get"](http_port, "/api/subsystem/execute/" + job_entry)
    record("BEH_06_BATCH_STEP", "batch orchestration execution",
           st == 200 and batch.get("returnCode") == 0
           and batch.get("status") == "SUCCESS",
           observed={k: batch.get(k) for k in ("component", "returnCode", "status")})
    st, xfr = mod["http_get"](http_port, "/api/execute/Bnk1tfn/execute")
    record("BEH_07_TRANSFER_EXEC", "BNK1TFN execution",
           st == 200 and xfr.get("returnCode") == 0 and xfr.get("status") == "SUCCESS",
           observed=xfr.get("status"))
    st_unknown, res_unknown = mod["http_get"](http_port, "/api/subsystem/execute/NO_SUCH_COMPONENT")
    record("BEH_08_UNKNOWN_404", "unknown component 404 contract",
           st_unknown == 200 and res_unknown.get("status") == "NOT_FOUND"
           and res_unknown.get("returnCode") == 404,
           observed_status=st_unknown,
           observed_body={k: res_unknown.get(k) for k in ("status", "returnCode", "error")})
    matrix = ["Bnk1cac", "Bnk1cca", "Bnk1dac", "Bnk1dcs", "Bnk1uac", "Bnkmenu", "Bankdata"]
    ok_n = 0
    failures = []
    for entry in matrix:
        try:
            st, res = mod["http_get"](http_port, "/api/subsystem/execute/" + entry)
            if st == 200 and res.get("returnCode") == 0:
                ok_n += 1
            else:
                failures.append({"entry": entry, "st": st,
                                 "rc": res.get("returnCode"),
                                 "status": res.get("status")})
        except Exception as e:
            failures.append({"entry": entry, "st": -1, "error": str(e)})
    record("BEH_09_EXEC_MATRIX", "exec matrix", ok_n == len(matrix),
           passed_entries="%d/%d" % (ok_n, len(matrix)),
           encountering_failures=failures[:5])
    logs = runner.stop()
    stages.append({"stage": "live_runtime_behavioral_verification",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "tests_executed": len(behavior),
                   "tests_passed": sum(1 for b in behavior if b["status"] == "PASSED"),
                   "runtime_log_lines": len(logs.splitlines())})
    return behavior, dict(rt)
