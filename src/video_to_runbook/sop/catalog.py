"""Lookup layer over the SAP catalogue, exposed to the planner as tools.

The catalogue is 399 KB and cannot go in a prompt, so the planner queries it
instead. Every function here is a tool the model calls while it writes a plan,
which is why the docstrings read as instructions: they are the only description
the model gets.

Results are capped. A tool that dumps 300 matches costs more context than the
prompt this design exists to avoid.
"""

import json

MAX_MATCHES = 40


class Catalog:
    def __init__(self, path: str = "catalog.json"):
        with open(path) as f:
            c = json.load(f)
        self.base_url: str = c["base_url"]
        self.entity_sets: dict[str, str] = c["entity_sets"]
        self.entity_types: dict[str, dict[str, str]] = c["entity_types"]
        self.complex_types: dict[str, dict[str, str]] = c["complex_types"]
        self.actions: list[str] = c["actions"]
        # Saved SQL queries reach data OData does not expose. Human-authored,
        # fetched by fetch_queries.py; absent until someone registers one.
        self.queries: dict[str, dict] = c.get("queries", {})

    def _cap(self, matches: list[str]) -> dict:
        out = {"matches": sorted(matches)[:MAX_MATCHES], "total": len(matches)}
        if len(matches) > MAX_MATCHES:
            out["note"] = f"{len(matches)} matches, showing {MAX_MATCHES}. Narrow the query."
        return out

    def find_entities(self, query: str) -> dict:
        q = query.lower()
        return self._cap([n for n in self.entity_sets if q in n.lower()])

    def describe_entity(self, entity_set: str) -> dict:
        type_name = self.entity_sets.get(entity_set)
        if type_name is None:
            near = [n for n in self.entity_sets if entity_set.lower() in n.lower()][:10]
            return {"error": f"no entity set named {entity_set!r}", "did_you_mean": sorted(near)}
        props = self.entity_types.get(type_name, {})
        return {
            "entity_set": entity_set,
            "entity_type": type_name,
            "property_count": len(props),
            "properties": props,
        }

    def find_fields(self, query: str, entity_set: str | None = None) -> dict:
        """Where does a field like this live? Answers questions the entity names cannot."""
        q = query.lower()
        if entity_set:
            d = self.describe_entity(entity_set)
            if "error" in d:
                return d
            return {
                "entity_set": entity_set,
                "matches": {k: v for k, v in d["properties"].items() if q in k.lower()},
            }
        hits = []
        for type_name, props in self.entity_types.items():
            for p, t in props.items():
                if q in p.lower():
                    hits.append(f"{type_name}.{p} ({t})")
        for type_name, props in self.complex_types.items():
            for p, t in props.items():
                if q in p.lower():
                    hits.append(f"{type_name}.{p} ({t}) [complex type]")
        return self._cap(hits)

    def describe_complex_type(self, name: str) -> dict:
        props = self.complex_types.get(name)
        if props is None:
            near = [n for n in self.complex_types if name.lower() in n.lower()][:10]
            return {"error": f"no complex type named {name!r}", "did_you_mean": sorted(near)}
        return {"complex_type": name, "property_count": len(props), "properties": props}

    def find_actions(self, query: str) -> dict:
        q = query.lower()
        return self._cap([a for a in self.actions if q in a.lower()])

    def find_queries(self, query: str = "") -> dict:
        if not self.queries:
            return {
                "matches": [],
                "total": 0,
                "note": "No saved SQL queries are registered on this system.",
            }
        q = query.lower()
        hits = [
            f"{c}: {d.get('SqlName') or ''}"
            for c, d in self.queries.items()
            if q in c.lower() or q in (d.get("SqlName") or "").lower()
        ]
        return self._cap(hits)

    def describe_query(self, code: str) -> dict:
        d = self.queries.get(code)
        if d is None:
            near = [c for c in self.queries if code.lower() in c.lower()][:10]
            return {"error": f"no saved query {code!r}", "did_you_mean": sorted(near)}
        params = [p.strip() for p in (d.get("ParamList") or "").split(",") if p.strip()]
        return {
            "code": code,
            "name": d.get("SqlName"),
            "parameters": params,
            "sql": d.get("SqlText"),
            "call": (
                f"GET SQLQueries('{code}')/List"
                + ("?" + "&".join(f"{p}=<value>" for p in params) if params else "")
            ),
        }


def register(agent, catalog: Catalog) -> None:
    """Attach the catalogue to an agent as tools."""

    @agent.tool_plain
    def find_entities(query: str) -> dict:
        """Find SAP entity sets whose name contains `query`, case-insensitive.

        Entity sets are what you put in an api_call `path`, e.g. "Orders".
        Start here when you know the business object but not its SAP name.
        """
        return catalog.find_entities(query)

    @agent.tool_plain
    def describe_entity(entity_set: str) -> dict:
        """List every property of an entity set, with its type.

        Call this before writing ANY $filter, $select or request body touching that
        entity. Use only the property names it returns. If a field you expected is
        absent, it does not exist on this entity; use find_fields to locate it, and
        do not invent it.
        """
        return catalog.describe_entity(entity_set)

    @agent.tool_plain
    def find_fields(query: str, entity_set: str = "") -> dict:
        """Find which types carry a property whose name contains `query`.

        Use this when you know the data you need but not where SAP keeps it, e.g.
        find_fields("quantity") or find_fields("date", entity_set="BatchNumberDetails").
        Results tagged [complex type] are nested structures inside a document, not
        entity sets you can GET directly.
        """
        return catalog.find_fields(query, entity_set or None)

    @agent.tool_plain
    def describe_complex_type(name: str) -> dict:
        """List the properties of a complex type, e.g. "DocumentLine" or "BatchNumber".

        Complex types are the nested objects inside a request body. A delivery note's
        lines are DocumentLine, and the lots on a line are BatchNumber. Call this
        before writing a nested body so the field names are real.
        """
        return catalog.describe_complex_type(name)

    @agent.tool_plain
    def find_queries(query: str = "") -> dict:
        """Find saved SQL queries registered on this SAP system.

        Saved queries reach data the OData entities do not expose, such as stock
        quantity per batch per warehouse. Call this whenever describe_entity shows
        that an entity lacks a field you need, BEFORE concluding the data is
        unreachable. Pass an empty query to list everything registered.
        """
        return catalog.find_queries(query)

    @agent.tool_plain
    def describe_query(code: str) -> dict:
        """Show a saved query's parameters, its SQL, and how to call it.

        Read the SELECT list in the returned SQL: those column names are the fields
        the rows will actually have, and they are what your transform must read.
        Invoke a saved query as an api_call on the SQLQueries entity, with a path
        like SQLQueries('TheCode')/List?Param='value'.
        """
        return catalog.describe_query(code)

    @agent.tool_plain
    def find_actions(query: str) -> dict:
        """Find SAP service actions (function imports) whose name contains `query`.

        These are operations rather than entities, e.g. approvals or close actions.
        """
        return catalog.find_actions(query)
