"""The operator's machine: the only place that talks to SAP.

The web app can compile a plan but cannot run one. It has no SAP credentials and
no route to the Service Layer. When someone presses "Run executor" it records
`exec_state = "requested"` on the run and stops there.

This worker polls the Modal Volume for those requests, runs the plan from here,
and writes the trace back. SAP credentials, the SAP hostname and the ERP session
never leave this machine, which is the point: nothing in the cloud is privileged
enough to create a document in your ERP.

    export B1_COMPANY=... B1_USER=... B1_PASS=...
    python sop_worker.py --insecure            # dry run unless the UI asked for live

Dry run still issues real GETs against SAP, so this is not a read-only worker.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).parent / "src"))

from video_to_runbook.sop.catalog import Catalog
from video_to_runbook.sop.execute import SAP, Executor, _tls_verify
from video_to_runbook.sop.validator import validate

VOLUME = "video-to-runbook-data"
RUNS = "/runs"


def read_json(volume: modal.Volume, path: str) -> dict | None:
    buf = io.BytesIO()
    try:
        volume.read_file_into_fileobj(path, buf)
    except FileNotFoundError:
        return None
    return json.loads(buf.getvalue())


def write_json(volume: modal.Volume, path: str, payload: dict) -> None:
    with volume.batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(json.dumps(payload, indent=1, default=str).encode()), path)


def pending(volume: modal.Volume) -> list[str]:
    """Run ids whose meta asks for an execution."""
    out = []
    for entry in volume.listdir(RUNS):
        run_id = Path(entry.path).name
        meta = read_json(volume, f"{RUNS}/{run_id}/meta.json")
        if meta and meta.get("exec_state") == "requested":
            out.append(run_id)
    return out


def run_one(volume: modal.Volume, run_id: str, catalog: Catalog, verify) -> None:
    meta = read_json(volume, f"{RUNS}/{run_id}/meta.json")
    compiled = read_json(volume, f"{RUNS}/{run_id}/plan.json")
    plan = (compiled or {}).get("plan")
    live = bool(meta.get("exec_live"))

    meta["exec_state"] = "running"
    write_json(volume, f"{RUNS}/{run_id}/meta.json", meta)
    print(f"[{run_id}] {'LIVE' if live else 'dry run'}: {(plan or {}).get('process_name')}")

    trace, error = [], None
    try:
        if plan is None:
            raise RuntimeError("no plan on this run")
        blocking = [e for e in validate(plan, catalog) if e.severity == "error"]
        if blocking:
            raise RuntimeError(f"plan has {len(blocking)} validation error(s): {blocking[0]}")

        inputs = {}
        for spec in plan.get("inputs", []):
            value = input(f"[{run_id}] {spec['name']} ({spec.get('description', '')}): ").strip()
            try:
                inputs[spec["name"]] = json.loads(value)
            except json.JSONDecodeError:
                inputs[spec["name"]] = value

        sap = SAP(
            catalog.base_url,
            os.environ["B1_COMPANY"],
            os.environ["B1_USER"],
            os.environ["B1_PASS"],
            verify=verify,
        )
        try:
            records = Executor(plan, sap, live=live).run(inputs)
        finally:
            sap.close()
        trace = [
            {
                "step_id": r.step_id,
                "kind": r.kind,
                "status": r.status,
                "detail": r.detail,
                "result": r.result,
            }
            for r in records
        ]
        for r in records:
            print(f"    {r.status.upper():10s} {r.step_id:26s} {r.detail[:90]}")
    except Exception as exc:  # noqa: BLE001  a failed run must not leave the UI spinning
        error = f"{type(exc).__name__}: {exc}"
        print(f"[{run_id}] failed: {error}", file=sys.stderr)

    write_json(volume, f"{RUNS}/{run_id}/trace.json", {"trace": trace})
    failed = [r for r in trace if r["status"] == "failed"]
    meta["exec_steps"] = len(trace)
    meta["exec_failed"] = len(failed)
    meta["exec_error"] = error or (failed[0]["detail"] if failed else None)
    meta["exec_state"] = "failed" if (error or failed) else "done"
    write_json(volume, f"{RUNS}/{run_id}/meta.json", meta)
    print(f"[{run_id}] {meta['exec_state']}: {len(trace)} step(s), {len(failed)} failed")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--catalog", default="catalog.json")
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="skip TLS verification; SAP B1's certificate is self-signed",
    )
    ap.add_argument("--ca", default=os.environ.get("B1_CA"))
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--once", action="store_true", help="drain what is pending, then exit")
    args = ap.parse_args()

    for key in ("B1_COMPANY", "B1_USER", "B1_PASS"):
        if key not in os.environ:
            print(f"set {key} in the environment", file=sys.stderr)
            return 2

    catalog = Catalog(args.catalog)
    verify = False if args.insecure else _tls_verify(args.ca)
    volume = modal.Volume.from_name(VOLUME)

    print(f"worker up: {catalog.base_url}  tls={'off' if verify is False else 'on'}")
    print("waiting for execution requests (Ctrl-C to stop)")
    while True:
        volume.reload()
        for run_id in pending(volume):
            run_one(volume, run_id, catalog, verify)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
