import json
import statistics
import time
from pathlib import Path

from autoforge_api.models import IntentExecutionRequest
from autoforge_api.service import AutoForgeApiService
from autoforge_composition.capability_router import CAPABILITY_MODERNIZATION

def main():
    service = AutoForgeApiService()
    workload_root = "/Users/kalachanddash/Developer/.autoforge-p20-workloads/playbook"

    runs = []
    print("Starting 3 canonical certification runs...")

    for i in range(1, 4):
        t0 = time.perf_counter()
        req = IntentExecutionRequest(
            prompt=f"Modernize legacy mainframe batch processing system (Certification Run {i}).",
            intent_type="modernization",
            context={
                "capability": CAPABILITY_MODERNIZATION,
                "legacy_source_root": workload_root,
            },
        )
        res = service.execute_intent_pipeline(req)
        total_sec = time.perf_counter() - t0
        man_path = Path("Modernization Output") / res.project_id / "DELIVERY-MANIFEST.json"
        man = json.loads(man_path.read_text())
        
        perf = man["performance_metrics"]
        model = man["model_metrics"]
        comp = man["project_completeness"]
        val = man["behavioral_equivalence"]
        
        run_data = {
            "run_index": i,
            "project_id": res.project_id,
            "status": res.status,
            "e2e_seconds": perf["total_wall_clock_seconds"],
            "throughput_nloc_per_hour": perf["end_to_end_nloc_per_hour"],
            "processed_files": comp["processed_files"],
            "discovered_files": comp["discovered_files"],
            "processed_nloc": perf["source_nloc"],
            "target_nloc": perf["target_nloc"],
            "m6_calls": model["actual_model_invocations"],
            "m6_in_tokens": model["input_tokens"],
            "m6_out_tokens": model["output_tokens"],
            "m6_total_tokens": model["input_tokens"] + model["output_tokens"],
            "m6_inference_seconds": model["inference_seconds"],
            "m6_status": model["m6_inference_status"],
            "byte_identical": val["byte_identical"],
            "accounts_out_hash": val["candidate_hashes"].get("accounts_out.dat"),
            "exceptions_hash": val["candidate_hashes"].get("exceptions.dat"),
        }
        runs.append(run_data)
        print(f"Run {i} complete: e2e={run_data['e2e_seconds']}s, throughput={run_data['throughput_nloc_per_hour']} NLOC/hr, M6={run_data['m6_status']}")

    e2e_times = [r["e2e_seconds"] for r in runs]
    throughputs = [r["throughput_nloc_per_hour"] for r in runs]

    summary = {
        "runs": runs,
        "e2e_seconds_stats": {
            "mean": round(statistics.mean(e2e_times), 4),
            "median": round(statistics.median(e2e_times), 4),
            "min": round(min(e2e_times), 4),
            "max": round(max(e2e_times), 4),
            "stdev": round(statistics.stdev(e2e_times), 4),
            "cv": round(statistics.stdev(e2e_times) / statistics.mean(e2e_times), 4),
        },
        "throughput_stats": {
            "mean": round(statistics.mean(throughputs), 2),
            "median": round(statistics.median(throughputs), 2),
            "min": round(min(throughputs), 2),
            "max": round(max(throughputs), 2),
            "stdev": round(statistics.stdev(throughputs), 2),
            "cv": round(statistics.stdev(throughputs) / statistics.mean(throughputs), 4),
        }
    }

    out_file = Path("certification_repeatability_3runs.json")
    out_file.write_text(json.dumps(summary, indent=2))
    print("SAVED", out_file)
    print("E2E Seconds Stats:", json.dumps(summary["e2e_seconds_stats"], indent=2))
    print("Throughput Stats:", json.dumps(summary["throughput_stats"], indent=2))

if __name__ == "__main__":
    main()
