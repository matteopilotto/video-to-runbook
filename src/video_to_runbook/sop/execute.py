"""Run a compiled plan. Dry-run by default: GETs are real, writes are not sent.

Writing this is what forces the IR to mean something. Four things were only
conventions until now, and this file is where they become definitions:

  references   ${inputs.x}, ${step_id.a.b[0]}, ${item} -- resolved by path walking
  run_if       a restricted expression over resolved values, never eval()
  for_each     the step runs per element and its result is a list, in order
  body_from    the referenced value becomes the whole request body

Transforms are model-written code, so they run in a subprocess with a timeout.
That bounds the combinatorial hang and keeps them out of this process's state.
It is not a security boundary: for that, run them in a modal.Sandbox with
networking disabled.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any

import httpx

REF = re.compile(r"\$\{([^}]*)\}")
TRANSFORM_TIMEOUT = 20


class ExecutionError(Exception):
    pass


# --------------------------------------------------------------------------
# references


def _path(ref: str) -> list:
    """'a.b[0].c' -> ['a', 'b', 0, 'c']"""
    parts: list = []
    for chunk in ref.split("."):
        name, *indexes = re.split(r"\[(\d+)\]", chunk)
        if name:
            parts.append(name)
        parts.extend(int(i) for i in indexes if i != "")
    return parts


def resolve(ref: str, scope: Scope) -> Any:
    parts = _path(ref)
    if not parts:
        raise ExecutionError(f"${{{ref}}} is empty")
    root, rest = parts[0], parts[1:]

    if root == "inputs":
        if not rest:
            raise ExecutionError("${inputs} must name an input")
        value = scope.inputs
    elif root == "item":
        if scope.item is _UNSET:
            raise ExecutionError("${item} used outside a for_each step")
        value = scope.item
    elif root in scope.results:
        value = scope.results[root]
    else:
        raise ExecutionError(f"${{{ref}}} does not resolve; known steps: {sorted(scope.results)}")

    for part in rest:
        try:
            value = value[part]
        except (KeyError, IndexError, TypeError) as e:
            raise ExecutionError(f"${{{ref}}} failed at {part!r}: {type(e).__name__}") from e
    return value


def substitute(value: Any, scope: Scope) -> Any:
    """Replace references inside a literal. A lone ${ref} keeps its native type."""
    if isinstance(value, str):
        whole = REF.fullmatch(value.strip())
        if whole:
            return resolve(whole.group(1), scope)
        return REF.sub(lambda m: str(resolve(m.group(1), scope)), value)
    if isinstance(value, dict):
        return {k: substitute(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, scope) for v in value]
    return value


# --------------------------------------------------------------------------
# run_if

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.List,
    ast.Tuple,
    ast.Call,
)
_ALLOWED_CALLS = {"len", "bool", "int", "float", "str", "abs"}
_BUILTINS = {
    k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
    for k in _ALLOWED_CALLS
}


def evaluate(expr: str, scope: Scope) -> bool:
    """Evaluate a guard. References are bound to names first, so the grammar
    stays tiny and no model-written string ever reaches eval()."""
    bindings: dict[str, Any] = {}

    def bind(m: re.Match) -> str:
        name = f"_v{len(bindings)}"
        bindings[name] = resolve(m.group(1), scope)
        return name

    tree = ast.parse(REF.sub(bind, expr), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExecutionError(f"{type(node).__name__} is not allowed in run_if: {expr!r}")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS
        ):
            raise ExecutionError(f"only {sorted(_ALLOWED_CALLS)} may be called in run_if")
        if isinstance(node, ast.Name) and node.id not in bindings and node.id not in _ALLOWED_CALLS:
            raise ExecutionError(f"unknown name {node.id!r} in run_if: {expr!r}")
    return bool(eval(compile(tree, "<run_if>", "eval"), {"__builtins__": _BUILTINS}, bindings))


# --------------------------------------------------------------------------
# transforms

_RUNNER = """
import json, sys
src = json.load(open(sys.argv[1]))
ns = {}
exec(src["code"], ns)
print(json.dumps(ns["transform"](**src["inputs"])))
"""


def run_transform(code: str, inputs: dict, timeout: int = TRANSFORM_TIMEOUT) -> Any:
    with tempfile.TemporaryDirectory() as d:
        payload, runner = os.path.join(d, "in.json"), os.path.join(d, "run.py")
        with open(payload, "w") as f:
            json.dump({"code": code, "inputs": inputs}, f)
        with open(runner, "w") as f:
            f.write(_RUNNER)
        try:
            p = subprocess.run(
                [sys.executable, runner, payload],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ExecutionError(
                f"transform exceeded {timeout}s; this is what an unbounded "
                "algorithm looks like at runtime"
            ) from None
    if p.returncode != 0:
        raise ExecutionError(
            f"transform raised: {p.stderr.strip().splitlines()[-1] if p.stderr else '?'}"
        )
    return json.loads(p.stdout)


# --------------------------------------------------------------------------
# SAP


class SAP:
    """Service Layer client. Session cookie auth, re-logs in when it expires."""

    def __init__(self, base_url: str, company: str, user: str, password: str, verify: Any = True):
        self.base_url = base_url.rstrip("/") + "/"
        self._creds = {"CompanyDB": company, "UserName": user, "Password": password}
        self._client = httpx.Client(verify=verify, timeout=60.0)
        self._logged_in = False

    def login(self) -> None:
        r = self._client.post(self.base_url + "Login", json=self._creds)
        if r.status_code != 200:
            try:  # SAP explains itself; the body has no secrets
                why = r.json()["error"]["message"]["value"]
            except (ValueError, KeyError, TypeError):  # not the shape SAP documents
                why = r.text[:200]
            raise ExecutionError(
                f"SAP login failed: HTTP {r.status_code}: {why} "
                f"(CompanyDB={self._creds['CompanyDB']!r}, UserName={self._creds['UserName']!r})"
            )
        self._logged_in = True

    def request(self, method: str, path: str, body: Any = None) -> Any:
        if not self._logged_in:
            self.login()
        url = self.base_url + path.lstrip("/")
        r = self._client.request(method, url, json=body)
        if r.status_code == 401:  # session expired
            self.login()
            r = self._client.request(method, url, json=body)
        if r.status_code >= 400:
            raise ExecutionError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def close(self) -> None:
        self._client.close()


# --------------------------------------------------------------------------
# execution


_UNSET = object()


class DryValue(dict):
    """Stands in for a write's response during a dry run.

    A simulated POST has no DocNum, so a later ${create_delivery.DocNum} would
    KeyError and abort the run one step from the end. Reading any field yields a
    visible placeholder instead, so the dry run finishes and shows what the rest
    of the plan would have done.
    """

    def __missing__(self, key):
        return f"<dry-run:{self.get('__step__', '?')}.{key}>"


@dataclass
class Scope:
    inputs: dict
    results: dict = field(default_factory=dict)
    item: Any = _UNSET


@dataclass
class Record:
    step_id: str
    kind: str
    status: str  # ran | skipped | simulated | stopped | failed
    detail: str = ""
    result: Any = None


class Executor:
    def __init__(self, plan: dict, sap: SAP | None, live: bool = False):
        self.plan, self.sap, self.live = plan, sap, live
        self.trace: list[Record] = []
        self.stopped: str | None = None

    def log(self, *a, **kw) -> Record:
        r = Record(*a, **kw)
        self.trace.append(r)
        return r

    # -- steps ------------------------------------------------------------

    def api_call(self, step: dict, scope: Scope) -> Any:
        path = substitute(step["path"], scope)
        method = step["method"]
        if step.get("body_from"):
            body = resolve(REF.fullmatch(step["body_from"].strip()).group(1), scope)
        else:
            body = substitute(step.get("body") or {}, scope) or None

        if method != "GET" and not self.live:
            self.log(
                step["step_id"],
                "api_call",
                "simulated",
                f"{method} {path}",
                {"__would_send__": body},
            )
            return DryValue(__dry_run__=True, __step__=step["step_id"])

        try:
            result = self.sap.request(method, path, body)
        except ExecutionError as err:
            # SAP says what it disliked but never what you sent. Without the body,
            # "Customer record not found" is a guessing game.
            if method != "GET":
                raise ExecutionError(f"{err}\n    sent: {json.dumps(body)}") from None
            raise
        self.log(step["step_id"], "api_call", "ran", f"{method} {path}", result)
        return result

    def transform(self, step: dict, scope: Scope) -> Any:
        args = {
            name: resolve(REF.fullmatch(ref.strip()).group(1), scope)
            for name, ref in (step.get("inputs") or {}).items()
        }
        result = run_transform(step["code"], args)
        self.log(step["step_id"], "transform", "ran", step.get("purpose", "")[:80], result)
        return result

    def notify(self, step: dict, scope: Scope) -> None:
        message = substitute(step["message"], scope)
        target = step.get("target")
        if target == "UNKNOWN" or not self.live:
            why = "target is UNKNOWN" if target == "UNKNOWN" else "dry run"
            self.log(step["step_id"], "notify", "simulated", f"[{why}] {message[:200]}")
            return
        r = httpx.post(target, json={"text": message}, timeout=30.0)
        self.log(
            step["step_id"],
            "notify",
            "ran" if r.status_code < 400 else "failed",
            f"HTTP {r.status_code}",
        )

    # -- driver -----------------------------------------------------------

    def run_step(self, step: dict, scope: Scope) -> None:
        sid, kind = step["step_id"], step["kind"]

        if step.get("run_if") and not evaluate(step["run_if"], scope):
            self.log(sid, kind, "skipped", f"run_if false: {step['run_if']}")
            return

        if kind == "stop":
            self.stopped = step.get("status", "success")
            self.log(sid, kind, "stopped", f"status={self.stopped}")
            return

        handler = {"api_call": self.api_call, "transform": self.transform, "notify": self.notify}[
            kind
        ]

        if step.get("for_each"):
            items = resolve(REF.fullmatch(step["for_each"].strip()).group(1), scope)
            if not isinstance(items, list):
                raise ExecutionError(f"for_each on {sid} got {type(items).__name__}, not a list")
            # The schema guarantees one result per element, in order.
            scope.results[sid] = [
                handler(step, Scope(scope.inputs, scope.results, item)) for item in items
            ]
            self.log(sid, kind, "ran", f"for_each over {len(items)} item(s)")
        else:
            result = handler(step, scope)
            if result is not None:
                scope.results[sid] = result

    def run(self, inputs: dict) -> list[Record]:
        scope = Scope(inputs)
        for step in self.plan.get("steps", []):
            if self.stopped:
                self.log(step["step_id"], step["kind"], "skipped", "plan already stopped")
                continue
            try:
                self.run_step(step, scope)
            except ExecutionError as e:
                self.log(step["step_id"], step["kind"], "failed", str(e))
                break
        return self.trace


# --------------------------------------------------------------------------
# cli


def _tls_verify(ca: str | None):
    """A --ca pointing at a missing file is a stale export, not an intent to crash."""
    if ca and os.path.exists(ca):
        return ca
    if ca:
        print(
            f"--ca {ca!r} does not exist; verifying against system roots. "
            "Use --insecure for SAP's self-signed cert.",
            file=sys.stderr,
        )
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan", help="compiled plan JSON (an ExecutionPlan)")
    ap.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="a plan input; repeat per input",
    )
    ap.add_argument(
        "--live", action="store_true", help="actually send writes to SAP. Off by default"
    )
    ap.add_argument("--force", action="store_true", help="run even if the validator reports errors")
    ap.add_argument(
        "--trace", metavar="FILE", help="write every step's full result to FILE, payloads included"
    )
    ap.add_argument(
        "--ca", default=os.environ.get("B1_CA"), help="PEM for the SAP cert. Defaults to $B1_CA"
    )
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="skip TLS verification, like curl -k. SAP B1's cert is self-signed",
    )
    args = ap.parse_args()

    try:
        with open(args.plan) as f:
            plan = json.load(f)
    except FileNotFoundError:
        print(f"no such plan file: {args.plan}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        size = os.path.getsize(args.plan)
        extra = " The file is empty; the compile probably failed." if size == 0 else ""
        print(f"{args.plan} is not valid JSON ({size} bytes): {e}.{extra}", file=sys.stderr)
        return 2

    plan = plan.get("plan", plan)  # accept a CompileResult too
    if not isinstance(plan, dict) or "steps" not in plan:
        print(f"{args.plan} does not look like a plan (no 'steps')", file=sys.stderr)
        return 2

    from video_to_runbook.sop.catalog import Catalog
    from video_to_runbook.sop.validator import validate

    catalog = Catalog()
    issues = validate(plan, catalog)
    blocking = [e for e in issues if e.severity == "error"]
    for e in issues:
        print(e, file=sys.stderr)
    if blocking and not args.force:
        print(f"\n{len(blocking)} error(s). Refusing to run; --force to override.", file=sys.stderr)
        return 2

    inputs = {}
    for pair in args.input:
        name, _, value = pair.partition("=")
        try:
            inputs[name] = json.loads(value)
        except json.JSONDecodeError:
            inputs[name] = value
    missing = [i["name"] for i in plan.get("inputs", []) if i["name"] not in inputs]
    if missing:
        print(f"missing --input for: {missing}", file=sys.stderr)
        return 2

    sap = None
    if args.live or any(s.get("method") == "GET" for s in plan.get("steps", [])):
        try:
            verify = False if args.insecure else _tls_verify(args.ca)
            sap = SAP(
                catalog.base_url,
                os.environ["B1_COMPANY"],
                os.environ["B1_USER"],
                os.environ["B1_PASS"],
                verify=verify,
            )
        except KeyError as e:
            print(f"set {e} in the environment to reach SAP", file=sys.stderr)
            return 2

    mode = "LIVE" if args.live else "DRY RUN (writes are not sent)"
    print(f"\n{mode}: {plan.get('process_name')}\n")
    try:
        trace = Executor(plan, sap, live=args.live).run(inputs)
    finally:
        if sap:
            sap.close()

    for r in trace:
        print(f"  {r.status.upper():10s} {r.step_id:28s} {r.detail}")
    if args.trace:
        with open(args.trace, "w") as f:
            json.dump(
                [
                    {
                        "step_id": r.step_id,
                        "kind": r.kind,
                        "status": r.status,
                        "detail": r.detail,
                        "result": r.result,
                    }
                    for r in trace
                ],
                f,
                indent=1,
                default=str,
            )
        print(f"\ntrace written to {args.trace}")
    failed = [r for r in trace if r.status == "failed"]
    print(f"\n{len(trace)} step(s), {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
