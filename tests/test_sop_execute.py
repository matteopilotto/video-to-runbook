import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import unittest
from video_to_runbook.sop.execute import (
    Scope,
    ExecutionError,
    evaluate,
    resolve,
    run_transform,
    substitute,
    _path,
)


class TestReferences(unittest.TestCase):
    def setUp(self):
        self.s = Scope(
            inputs={"order_number": 42},
            results={"get_order": {"value": [{"DocEntry": 7, "Lines": [{"Q": 3}]}]}},
        )

    def test_path_parsing(self):
        self.assertEqual(_path("a.b[0].c"), ["a", "b", 0, "c"])

    def test_input_and_nested_step_result(self):
        self.assertEqual(resolve("inputs.order_number", self.s), 42)
        self.assertEqual(resolve("get_order.value[0].DocEntry", self.s), 7)
        self.assertEqual(resolve("get_order.value[0].Lines[0].Q", self.s), 3)

    def test_item_only_inside_a_loop(self):
        with self.assertRaises(ExecutionError):
            resolve("item", self.s)
        self.assertEqual(resolve("item.x", Scope({}, {}, {"x": 1})), 1)

    def test_unknown_root_names_what_is_available(self):
        with self.assertRaisesRegex(ExecutionError, "known steps"):
            resolve("nope.x", self.s)

    def test_lone_reference_keeps_its_type(self):
        self.assertEqual(substitute("${inputs.order_number}", self.s), 42)  # int
        self.assertEqual(substitute("order ${inputs.order_number}", self.s), "order 42")

    def test_substitution_recurses_into_structures(self):
        got = substitute({"a": ["${inputs.order_number}"]}, self.s)
        self.assertEqual(got, {"a": [42]})


class TestRunIf(unittest.TestCase):
    def setUp(self):
        self.s = Scope(inputs={}, results={"c": {"exists": False, "rows": [1, 2]}})

    def test_truth_and_negation(self):
        self.assertFalse(evaluate("${c.exists}", self.s))
        self.assertTrue(evaluate("not ${c.exists}", self.s))

    def test_comparison_and_len(self):
        self.assertTrue(evaluate("len(${c.rows}) == 2", self.s))
        self.assertFalse(evaluate("len(${c.rows}) > 5", self.s))

    def test_rejects_attribute_access(self):
        with self.assertRaises(ExecutionError):
            evaluate("${c.rows}.__class__", self.s)

    def test_rejects_arbitrary_calls(self):
        with self.assertRaisesRegex(ExecutionError, "may be called"):
            evaluate("open('/etc/passwd')", self.s)

    def test_rejects_unbound_names(self):
        with self.assertRaisesRegex(ExecutionError, "unknown name"):
            evaluate("secret == 1", self.s)


class TestTransforms(unittest.TestCase):
    def test_runs_and_returns_json(self):
        self.assertEqual(
            run_transform("def transform(a, b):\n    return {'s': a + b}", {"a": 1, "b": 2}),
            {"s": 3},
        )

    def test_reports_the_exception(self):
        with self.assertRaisesRegex(ExecutionError, "transform raised"):
            run_transform("def transform():\n    raise ValueError('boom')", {})

    def test_timeout_bounds_a_runaway(self):
        # The combinatorial hang, made survivable.
        with self.assertRaisesRegex(ExecutionError, "exceeded"):
            run_transform("def transform():\n    while True: pass", {}, timeout=2)


if __name__ == "__main__":
    unittest.main()
