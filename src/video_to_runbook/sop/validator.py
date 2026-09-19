"""Static checks on a compiled plan, before anything runs.

Answers the one question a planner cannot answer about itself: does every name
in this plan exist? Deterministic, no model, no network. The output is meant to
be fed back to the planner as compile errors, so each message says what is wrong
and what would be right.

Works on a raw dict rather than a parsed ExecutionPlan, because a plan that
fails schema validation is exactly the kind we most want a report on.
"""

import ast
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from video_to_runbook.sop.catalog import Catalog
from video_to_runbook.sop.plan_schema import ExecutionPlan

# OData operators and functions are not field names.
ODATA_WORDS = {
    "eq",
    "ne",
    "gt",
    "ge",
    "lt",
    "le",
    "and",
    "or",
    "not",
    "null",
    "true",
    "false",
    "asc",
    "desc",
    "add",
    "sub",
    "mul",
    "div",
    "mod",
    "substringof",
    "startswith",
    "endswith",
    "contains",
    "length",
    "indexof",
    "replace",
    "substring",
    "tolower",
    "toupper",
    "trim",
    "concat",
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "round",
    "floor",
    "ceiling",
}

REF = re.compile(r"\$\{([^}]*)\}")


@dataclass
class Error:
    severity: Literal["error", "warning"]
    code: str
    message: str
    step_id: str | None = None

    def __str__(self) -> str:
        where = f"[{self.step_id}] " if self.step_id else ""
        return f"{self.severity.upper():7s} {self.code:20s} {where}{self.message}"


class _Validator:
    def __init__(self, plan: dict, catalog: Catalog):
        self.plan = plan
        self.cat = catalog
        self.errors: list[Error] = []
        self.steps: list[dict] = plan.get("steps") or []
        # A reference names a plan input, an earlier step, or the loop element.
        self.declared_inputs: set[str] = {i.get("name") for i in plan.get("inputs") or []}
        self.declared_inputs.discard(None)
        self.step_index: dict[str, int] = {
            s.get("step_id"): i for i, s in enumerate(self.steps) if s.get("step_id")
        }
        # Only these kinds produce a value another step can read.
        self.produces_value: set[str] = {
            s["step_id"]
            for s in self.steps
            if s.get("step_id") and s.get("kind") in ("api_call", "transform")
        }
        # A write exists for its side effect, so nothing reading it is not a defect.
        self.side_effect_only: set[str] = {
            s["step_id"]
            for s in self.steps
            if s.get("kind") == "api_call" and s.get("method") in ("POST", "PATCH", "DELETE")
        }
        self.referenced: set[str] = set()
        # Every property name that exists anywhere in SAP, for the spelling check.
        self.all_props: set[str] = set()
        for props in list(catalog.entity_types.values()) + list(catalog.complex_types.values()):
            self.all_props.update(props)

    def add(self, sev, code, msg, step_id=None):
        self.errors.append(Error(sev, code, msg, step_id))

    # -- names -------------------------------------------------------------

    def entity_props(self, entity_set: str) -> dict | None:
        type_name = self.cat.entity_sets.get(entity_set)
        return self.cat.entity_types.get(type_name) if type_name else None

    def check_entity(self, step: dict) -> dict | None:
        name = step.get("entity")
        props = self.entity_props(name)
        if props is None:
            near = self.cat.find_entities(name or "")["matches"][:5]
            hint = f" Did you mean {near}?" if near else ""
            self.add("error", "UNKNOWN_ENTITY", f"no entity set {name!r}.{hint}", step["step_id"])
            return None
        # `path` is relative to base_url. A leading slash or scheme means the
        # executor would concatenate the base path twice.
        path = step.get("path", "")
        if path.startswith(("http://", "https://", "/")):
            self.add(
                "error",
                "PATH_NOT_RELATIVE",
                f"path {path[:40]!r} must be relative to base_url "
                f"({self.cat.base_url}); drop the leading prefix",
                step["step_id"],
            )
            path = path.lstrip("/")
            base = self.cat.base_url.split("//", 1)[-1].split("/", 1)[-1]
            if base and path.startswith(base):
                path = path[len(base) :]
        # The path should address the same entity it declares.
        head = re.split(r"[(?/]", path, 1)[0]
        if head and head != name:
            self.add(
                "error",
                "PATH_ENTITY_MISMATCH",
                f"entity is {name!r} but path starts with {head!r}",
                step["step_id"],
            )
        return props

    def path_fields(self, path: str) -> set[str]:
        """Field names referenced by $filter / $select / $orderby / $expand."""
        found: set[str] = set()
        for key, chunk in re.findall(r"\$(filter|select|orderby|expand)=([^&]*)", path):
            chunk = REF.sub(" ", chunk)  # drop ${...} references
            chunk = re.sub(r"'[^']*'", " ", chunk)  # drop quoted literals
            if key in ("select", "expand"):
                found.update(t.strip() for t in chunk.split(",") if t.strip())
            else:
                found.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", chunk))
        return {f for f in found if f.lower() not in ODATA_WORDS and not f.isdigit()}

    def check_fields(self, step: dict, props: dict):
        entity = step["entity"]
        for field in sorted(self.path_fields(step.get("path", ""))):
            if field not in props:
                where = self.where_does_it_live(field)
                self.add(
                    "error",
                    "UNKNOWN_FIELD",
                    f"{entity} has no field {field!r}.{where}",
                    step["step_id"],
                )
        for field in sorted(step.get("body") or {}):  # body_from is opaque until runtime
            if field not in props:
                self.add(
                    "error",
                    "UNKNOWN_FIELD",
                    f"{entity} body key {field!r} is not a property of "
                    f"{self.cat.entity_sets[entity]}.",
                    step["step_id"],
                )

    def check_saved_query(self, step: dict):
        """A SQLQueries('X')/List call must name a registered query and pass its params."""
        m = re.search(r"SQLQueries\('([^']+)'\)", step.get("path", ""))
        if not m:
            return
        code = m.group(1)
        if not self.cat.queries:
            # Silence here reads as approval, and the call will 404 at runtime.
            self.add(
                "warning",
                "QUERY_NOT_REGISTERED",
                f"plan calls saved query {code!r} but no saved queries are in the "
                "catalogue. Create it in SAP, then run fetch_queries.py",
                step["step_id"],
            )
            return
        spec = self.cat.queries.get(code)
        if spec is None:
            self.add(
                "error",
                "UNKNOWN_QUERY",
                f"no saved query {code!r}. Registered: {sorted(self.cat.queries)}",
                step["step_id"],
            )
            return
        supplied = set(re.findall(r"[?&]([A-Za-z_][A-Za-z0-9_]*)=", step["path"]))
        for p in (x.strip() for x in (spec.get("ParamList") or "").split(",")):
            if p and p not in supplied:
                self.add(
                    "error",
                    "MISSING_QUERY_PARAM",
                    f"saved query {code!r} requires parameter {p!r}",
                    step["step_id"],
                )

    def check_body(self, step: dict):
        body, body_from = step.get("body") or {}, step.get("body_from")
        if body and body_from:
            self.add(
                "error",
                "BODY_CONFLICT",
                "body and body_from are both set; use exactly one",
                step["step_id"],
            )
        if body_from is not None and not REF.fullmatch(str(body_from).strip()):
            self.add(
                "error",
                "BODY_FROM_NOT_REF",
                f"body_from is {body_from!r}; it must be a single ${{...}} reference",
                step["step_id"],
            )
        if step.get("method") in ("POST", "PATCH") and not body and not body_from:
            self.add(
                "error",
                "EMPTY_BODY",
                f"{step['method']} writes nothing: set body, or body_from if an earlier "
                "transform built the payload",
                step["step_id"],
            )

    # -- type inference ----------------------------------------------------

    def ref_type(self, ref: str) -> str | None:
        chain = self.ref_type_chain(ref)
        return chain[-1] if chain else None

    def ref_type_chain(self, ref: str) -> list:
        """Walk a ${...} path through the SAP type graph and name the type of the
        records it ends at. Returns None whenever the shape cannot be proved, so a
        guess never becomes an error."""
        parts: list = []
        for chunk in ref.split("."):
            name, *idx = re.split(r"\[(\d+)\]", chunk)
            if name:
                parts.append(name)
            parts.extend(int(i) for i in idx if i != "")
        if not parts:
            return []
        root, rest = parts[0], parts[1:]

        i = self.step_index.get(root)
        if i is None:
            return []
        step = self.steps[i]
        if step.get("kind") != "api_call" or step.get("for_each"):
            return []  # a looped step yields a list of responses
        if step.get("entity") == "SQLQueries":
            return []  # shape is the SELECT list, not the entity
        if "value" not in rest:
            return []  # still the OData envelope, not records

        type_name = self.cat.entity_sets.get(step["entity"])
        chain = [type_name] if type_name else []
        for part in rest:
            if isinstance(part, int) or part == "value":
                continue  # collection element / OData envelope
            props = self.cat.entity_types.get(type_name) or self.cat.complex_types.get(type_name)
            if not props:
                return []
            nxt = props.get(part)
            if nxt in self.cat.complex_types or nxt in self.cat.entity_types:
                type_name = nxt
                chain.append(type_name)
            else:
                return []  # primitive, or unknown
        return chain

    def _element_aliases(self, tree: ast.AST, arg: str) -> set:
        """Names that hold one element of `arg`: loop variables and x = arg[i]."""
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                it = node.iter
                if isinstance(it, ast.Name) and it.id == arg and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
                if (
                    isinstance(it, ast.Call)
                    and isinstance(it.func, ast.Name)
                    and it.func.id == "enumerate"
                    and it.args
                    and isinstance(it.args[0], ast.Name)
                    and it.args[0].id == arg
                    and isinstance(node.target, ast.Tuple)
                    and len(node.target.elts) == 2
                    and isinstance(node.target.elts[1], ast.Name)
                ):
                    names.add(node.target.elts[1].id)
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Subscript)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == arg
            ):
                names.add(node.targets[0].id)
        return names

    def _fields_read(self, tree: ast.AST, arg: str, aliases: set) -> set:
        def is_element(e) -> bool:
            if isinstance(e, ast.Name) and e.id in aliases:
                return True
            return (
                isinstance(e, ast.Subscript)
                and isinstance(e.value, ast.Name)
                and e.value.id == arg
                and not (isinstance(e.slice, ast.Constant) and isinstance(e.slice.value, str))
            )

        fields = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
                and is_element(node.value)
            ):
                fields.add(node.slice.value)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and is_element(node.func.value)
            ):
                fields.add(node.args[0].value)
        return fields

    def check_transform_inputs(self, step: dict, tree: ast.AST):
        """A field that is real, but not on the type the argument actually holds,
        reads as None at runtime and SAP rejects the document."""
        for arg, ref in (step.get("inputs") or {}).items():
            m = REF.fullmatch(str(ref).strip())
            if not m:
                continue
            chain = self.ref_type_chain(m.group(1))
            if not chain:
                continue
            type_name = chain[-1]
            props = self.cat.entity_types.get(type_name) or self.cat.complex_types.get(type_name)
            if not props:
                continue
            aliases = self._element_aliases(tree, arg)
            for field in sorted(self._fields_read(tree, arg, aliases)):
                if field in props:
                    continue
                parent = next(
                    (
                        t
                        for t in reversed(chain[:-1])
                        if field
                        in (self.cat.entity_types.get(t) or self.cat.complex_types.get(t) or {})
                    ),
                    None,
                )
                if parent:
                    hint = (
                        f" It is on {parent}, the parent of this collection: pass a "
                        f"reference to the {parent} itself as another input."
                    )
                else:
                    hint = self.where_does_it_live(field)
                self.add(
                    "error",
                    "FIELD_NOT_ON_TYPE",
                    f"{arg!r} holds {type_name} records, which have no field {field!r}.{hint}",
                    step["step_id"],
                )

    def where_does_it_live(self, field: str) -> str:
        hits = self.cat.find_fields(field)["matches"][:3]
        exact = [h for h in hits if h.split(".", 1)[1].split(" ")[0] == field]
        if exact:
            return f" It exists on {', '.join(exact[:2])}."
        return " No SAP type has a field by that name." if not hits else ""

    # -- references --------------------------------------------------------

    def refs_in(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return REF.findall(value)
        if isinstance(value, dict):
            return [r for v in value.values() for r in self.refs_in(v)]
        if isinstance(value, list):
            return [r for v in value for r in self.refs_in(v)]
        return []

    def check_refs(self, step: dict, in_loop: bool):
        scanned = {k: v for k, v in step.items() if k not in ("code", "tests", "reason")}
        for ref in self.refs_in(scanned):
            parts = re.split(r"[.\[]", ref, 1)
            root = parts[0]
            self.referenced.add(root)

            if root == "item":
                if not in_loop:
                    self.add(
                        "error",
                        "ITEM_OUTSIDE_LOOP",
                        "${item} used but the step has no for_each",
                        step["step_id"],
                    )
                continue

            if root == "inputs":
                name = re.split(r"[.\[]", parts[1])[0] if len(parts) > 1 else ""
                if not name:
                    self.add(
                        "error",
                        "BAD_INPUT_REF",
                        "${inputs} must name an input, e.g. ${inputs.order_number}",
                        step["step_id"],
                    )
                elif name not in self.declared_inputs:
                    self.add(
                        "error",
                        "UNKNOWN_INPUT",
                        f"{name!r} is not a declared plan input. Declared: "
                        f"{sorted(self.declared_inputs)}",
                        step["step_id"],
                    )
                continue

            if root in self.step_index:
                if self.step_index[root] >= self.index:
                    self.add(
                        "error",
                        "FORWARD_REF",
                        f"${{{ref}}} refers to a step that runs later",
                        step["step_id"],
                    )
                elif root not in self.produces_value:
                    kind = self.steps[self.step_index[root]].get("kind")
                    self.add(
                        "error",
                        "NO_VALUE",
                        f"${{{ref}}} reads step {root!r}, but a {kind!r} step produces no value",
                        step["step_id"],
                    )
                continue

            if root in self.declared_inputs:
                hint = f" {root!r} is a plan input; reference it as ${{inputs.{root}}}."
            else:
                hint = (
                    f" A reference names a plan input (${{inputs.X}}), an earlier step "
                    f"(${{step_id...}}), or ${{item}}. Earlier steps: "
                    f"{sorted(k for k, v in self.step_index.items() if v < self.index)}"
                )
            self.add(
                "error", "UNRESOLVED_REF", f"${{{ref}}} does not resolve.{hint}", step["step_id"]
            )

    # -- code --------------------------------------------------------------

    def check_code(self, step: dict):
        code = step.get("code") or ""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            self.add("error", "TRANSFORM_SYNTAX", f"code does not parse: {e}", step["step_id"])
            return
        if not any(isinstance(n, ast.FunctionDef) and n.name == "transform" for n in tree.body):
            self.add(
                "error", "NO_TRANSFORM_FN", "code must define `def transform(...)`", step["step_id"]
            )
        self.check_field_literals(step, tree)
        self.check_transform_inputs(step, tree)

        tests = step.get("tests") or []
        if not tests:
            self.add("warning", "NO_TESTS", "transform has no tests", step["step_id"])
        for t in tests:
            body = t.get("test_code")
            if body is None:
                self.add(
                    "error",
                    "TEST_NOT_CODE",
                    f"test {t.get('name')!r} has no test_code; typed input/expected "
                    "pairs are not runnable",
                    step["step_id"],
                )
                continue
            try:
                tt = ast.parse(body)
            except SyntaxError as e:
                self.add(
                    "error",
                    "TEST_SYNTAX",
                    f"test {t.get('name')!r} does not parse: {e}",
                    step["step_id"],
                )
                continue
            if not any(isinstance(n, ast.FunctionDef) and n.name == "test" for n in tt.body):
                self.add(
                    "error",
                    "NO_TEST_FN",
                    f"test {t.get('name')!r} must define `def test(transform):`",
                    step["step_id"],
                )

    def check_field_literals(self, step: dict, tree: ast.AST):
        """A string used as a field name that exists nowhere in SAP is a guess."""
        literals: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                literals.add(node.args[0].value)
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                literals.add(node.slice.value)
        for node in ast.walk(tree):
            fn = node.func if isinstance(node, ast.Call) else None
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name in ("combinations", "permutations", "product"):
                self.add(
                    "error",
                    "COMBINATORIAL",
                    f"code calls {name}() over live data; cost grows exponentially and "
                    "hangs on realistic record counts. Rewrite the algorithm so its cost "
                    "grows at worst with n log n in the number of records",
                    step["step_id"],
                )
                break
        for lit in sorted(literals):
            if lit and lit[0].isupper() and lit not in self.all_props:
                self.add(
                    "warning",
                    "SUSPECT_FIELD",
                    f"code reads {lit!r}, which is not a property of any SAP type",
                    step["step_id"],
                )

    # -- run ---------------------------------------------------------------

    def run(self) -> list[Error]:
        try:
            ExecutionPlan.model_validate(self.plan)
        except ValidationError as e:
            for err in e.errors()[:10]:
                self.add("error", "SCHEMA", f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}")

        seen_ids: set[str] = set()
        for i, step in enumerate(self.steps):
            self.index = i
            sid = step.get("step_id")
            if sid in seen_ids:
                self.add("error", "DUPLICATE_STEP_ID", f"step_id {sid!r} used twice", sid)
            if sid in ("inputs", "item"):
                self.add(
                    "error",
                    "STEP_ID_RESERVED",
                    f"step_id {sid!r} is reserved and shadows references",
                    sid,
                )
            seen_ids.add(sid)

            self.check_refs(step, in_loop=bool(step.get("for_each")))

            kind = step.get("kind")
            if kind == "api_call":
                if step.get("entity") == "SQLQueries":
                    self.check_saved_query(step)
                props = self.check_entity(step)
                if props is not None:
                    self.check_fields(step, props)
                self.check_body(step)
            elif kind == "transform":
                self.check_code(step)
                for arg, ref in (step.get("inputs") or {}).items():
                    if not REF.fullmatch(ref.strip()):
                        self.add(
                            "warning",
                            "LITERAL_INPUT",
                            f"input {arg!r} is {ref!r}, not a ${{...}} reference",
                            sid,
                        )
            elif kind == "notify" and step.get("target") == "UNKNOWN":
                self.add("warning", "UNKNOWN_TARGET", "notify target is UNKNOWN", sid)

        for sid in self.produces_value - self.side_effect_only:
            if sid not in self.referenced:
                self.add(
                    "warning", "DEAD_STEP", f"step {sid!r} produces a value nothing reads", sid
                )
        return self.errors


def validate(plan: dict, catalog: Catalog) -> list[Error]:
    return _Validator(plan, catalog).run()


def format_for_model(errors: list[Error]) -> str:
    """Render findings as compile errors the planner can act on."""
    errs = [e for e in errors if e.severity == "error"]
    warns = [e for e in errors if e.severity == "warning"]
    if not errs and not warns:
        return "Plan validates."

    def line(e: Error) -> str:
        where = f" in step '{e.step_id}'" if e.step_id else ""
        return f"- {e.code}{where}: {e.message}"

    out = []
    if errs:
        out += [
            (
                f"Your plan failed validation with {len(errs)} error(s). "
                "These are facts checked against the real SAP schema, not opinions."
            ),
            "",
        ]
        out += [line(e) for e in errs]
        out += [
            "",
            (
                "Fix every error above and re-emit the COMPLETE plan, including the "
                "steps that were already correct. Use the catalogue tools to confirm "
                "any name you are unsure of rather than guessing again."
            ),
        ]
    if warns:
        out += ["", f"{len(warns)} warning(s), not blocking, fix where you reasonably can:"]
        out += [line(e) for e in warns]
    return "\n".join(out)
