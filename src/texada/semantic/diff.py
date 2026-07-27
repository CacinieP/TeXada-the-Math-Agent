"""Structural diff for semantic math units."""

from __future__ import annotations

from collections import Counter

from texada.semantic.model import (
    SemanticChange,
    SemanticDiff,
    SemanticDocument,
    SemanticUnit,
)
from texada.semantic.parser import SemanticParser


class SemanticDiffer:
    """Role-aware weighted edit distance over ordered semantic-unit trees.

    Equal subtrees are pruned by fingerprint. Named mathematical roles are
    matched before the remaining ordered children are aligned with dynamic
    programming, which prevents an inserted token from shifting every later
    comparison.
    """

    _KIND_WEIGHTS = {
        "sequence": 0.25,
        "group": 0.5,
        "symbol": 1.0,
        "number": 1.0,
        "command": 2.0,
        "script": 2.5,
        "root": 3.5,
        "fraction": 4.0,
        "integral": 4.0,
        "summation": 3.5,
        "product": 3.5,
        "limit": 3.0,
        "environment": 4.0,
        "row": 1.5,
        "cell": 1.25,
        "syntax": 4.0,
    }
    _CRITICAL_ROLES = {
        "numerator",
        "denominator",
        "radicand",
        "index",
        "lower_bound",
        "upper_bound",
        "subscript",
        "superscript",
    }

    def __init__(self, parser: SemanticParser | None = None):
        self.parser = parser or SemanticParser()

    def diff(
        self,
        before: str | SemanticDocument,
        after: str | SemanticDocument,
    ) -> SemanticDiff:
        before_doc = self.parser.parse(before) if isinstance(before, str) else before
        after_doc = self.parser.parse(after) if isinstance(after, str) else after
        changes: list[SemanticChange] = []
        weighted_cost = self._compare(before_doc.root, after_doc.root, "root", changes)
        if before_doc.diagnostics != after_doc.diagnostics:
            syntax_cost = self._KIND_WEIGHTS["syntax"]
            changes.append(
                SemanticChange(
                    operation="repair",
                    path="root.syntax",
                    unit_kind="syntax",
                    before="; ".join(before_doc.diagnostics) or None,
                    after="; ".join(after_doc.diagnostics) or None,
                    cost=syntax_cost,
                )
            )
            weighted_cost += syntax_cost
        normalization_weight = max(
            self._tree_weight(before_doc.root),
            self._tree_weight(after_doc.root),
            1.0,
        )
        normalized_distance = min(weighted_cost / normalization_weight, 1.0)
        return SemanticDiff(
            equivalent=not changes,
            changes=changes,
            before=before_doc,
            after=after_doc,
            weighted_cost=weighted_cost,
            normalization_weight=normalization_weight,
            normalized_distance=normalized_distance,
            semantic_similarity=max(0.0, 1.0 - normalized_distance),
        )

    def _compare(
        self,
        before: SemanticUnit,
        after: SemanticUnit,
        path: str,
        changes: list[SemanticChange],
    ) -> float:
        if before.fingerprint() == after.fingerprint():
            return 0.0

        if before.kind != after.kind:
            cost = max(self._tree_weight(before), self._tree_weight(after))
            changes.append(
                SemanticChange(
                    operation="replace",
                    path=path,
                    unit_kind=after.kind,
                    role=after.role or before.role,
                    before=before.label,
                    after=after.label,
                    cost=cost,
                )
            )
            return cost

        cost = 0.0
        if before.value != after.value:
            change_cost = max(0.5, self._node_weight(after) * 0.75)
            changes.append(
                SemanticChange(
                    operation="update",
                    path=path,
                    unit_kind=after.kind,
                    role=after.role or before.role,
                    before=before.value,
                    after=after.value,
                    cost=change_cost,
                )
            )
            cost += change_cost

        if before.role != after.role:
            change_cost = self._role_cost(before.role, after.role)
            changes.append(
                SemanticChange(
                    operation="update",
                    path=f"{path}.role",
                    unit_kind=after.kind,
                    role=after.role,
                    before=before.role or None,
                    after=after.role or None,
                    cost=change_cost,
                )
            )
            cost += change_cost

        if before.attributes != after.attributes:
            change_cost = 0.5
            changes.append(
                SemanticChange(
                    operation="update",
                    path=f"{path}.attributes",
                    unit_kind=after.kind,
                    role=after.role or before.role,
                    before=str(before.attributes),
                    after=str(after.attributes),
                    cost=change_cost,
                )
            )
            cost += change_cost

        cost += self._compare_children(before, after, path, changes)
        return cost

    def _compare_children(
        self,
        before: SemanticUnit,
        after: SemanticUnit,
        path: str,
        changes: list[SemanticChange],
    ) -> float:
        cost = 0.0
        before_role_counts = Counter(child.role for child in before.children if child.role)
        after_role_counts = Counter(child.role for child in after.children if child.role)
        shared_roles = {
            role
            for role in before_role_counts.keys() & after_role_counts.keys()
            if before_role_counts[role] == after_role_counts[role] == 1
        }
        matched_before: set[int] = set()
        matched_after: set[int] = set()
        before_by_role = {child.role: index for index, child in enumerate(before.children)}

        for after_index, after_child in enumerate(after.children):
            if after_child.role not in shared_roles:
                continue
            before_index = before_by_role[after_child.role]
            before_child = before.children[before_index]
            matched_before.add(before_index)
            matched_after.add(after_index)
            cost += self._compare(
                before_child,
                after_child,
                f"{path}.{after_child.role}",
                changes,
            )

        before_remaining = [
            (index, child)
            for index, child in enumerate(before.children)
            if index not in matched_before
        ]
        after_remaining = [
            (index, child)
            for index, child in enumerate(after.children)
            if index not in matched_after
        ]
        cost += self._align_ordered_children(
            before_remaining,
            after_remaining,
            path,
            changes,
        )
        return cost

    def _align_ordered_children(
        self,
        before: list[tuple[int, SemanticUnit]],
        after: list[tuple[int, SemanticUnit]],
        parent_path: str,
        changes: list[SemanticChange],
    ) -> float:
        rows = len(before) + 1
        columns = len(after) + 1
        costs = [[0.0] * columns for _ in range(rows)]
        choices = [[""] * columns for _ in range(rows)]

        for row in range(1, rows):
            costs[row][0] = costs[row - 1][0] + self._tree_weight(before[row - 1][1])
            choices[row][0] = "remove"
        for column in range(1, columns):
            costs[0][column] = (
                costs[0][column - 1] + self._tree_weight(after[column - 1][1])
            )
            choices[0][column] = "add"

        for row in range(1, rows):
            for column in range(1, columns):
                before_child = before[row - 1][1]
                after_child = after[column - 1][1]
                candidates = (
                    (
                        costs[row - 1][column - 1]
                        + self._pairing_cost(before_child, after_child),
                        0,
                        "match",
                    ),
                    (
                        costs[row - 1][column] + self._tree_weight(before_child),
                        1,
                        "remove",
                    ),
                    (
                        costs[row][column - 1] + self._tree_weight(after_child),
                        2,
                        "add",
                    ),
                )
                chosen_cost, _, choice = min(candidates)
                costs[row][column] = chosen_cost
                choices[row][column] = choice

        operations: list[
            tuple[
                str,
                tuple[int, SemanticUnit] | None,
                tuple[int, SemanticUnit] | None,
            ]
        ] = []
        row = len(before)
        column = len(after)
        while row or column:
            choice = choices[row][column]
            if choice == "match":
                operations.append(("match", before[row - 1], after[column - 1]))
                row -= 1
                column -= 1
            elif choice == "remove":
                operations.append(("remove", before[row - 1], None))
                row -= 1
            else:
                operations.append(("add", None, after[column - 1]))
                column -= 1

        total = 0.0
        for operation, before_item, after_item in reversed(operations):
            if operation == "match" and before_item and after_item:
                before_index, before_child = before_item
                after_index, after_child = after_item
                child_path = self._paired_path(
                    parent_path,
                    before_child,
                    after_child,
                    before_index,
                    after_index,
                )
                total += self._compare(before_child, after_child, child_path, changes)
            elif operation == "remove" and before_item:
                index, child = before_item
                change_cost = self._tree_weight(child)
                changes.append(
                    SemanticChange(
                        operation="remove",
                        path=self._child_path(parent_path, child, index),
                        unit_kind=child.kind,
                        role=child.role,
                        before=child.label,
                        cost=change_cost,
                    )
                )
                total += change_cost
            elif operation == "add" and after_item:
                index, child = after_item
                change_cost = self._tree_weight(child)
                changes.append(
                    SemanticChange(
                        operation="add",
                        path=self._child_path(parent_path, child, index),
                        unit_kind=child.kind,
                        role=child.role,
                        after=child.label,
                        cost=change_cost,
                    )
                )
                total += change_cost
        return total

    def _pairing_cost(self, before: SemanticUnit, after: SemanticUnit) -> float:
        if before.fingerprint() == after.fingerprint():
            return 0.0
        delete_and_add = self._tree_weight(before) + self._tree_weight(after)
        if before.role and after.role and before.role != after.role:
            return delete_and_add
        if before.kind != after.kind:
            return min(delete_and_add, max(self._tree_weight(before), self._tree_weight(after)))

        estimate = 0.0
        if before.value != after.value:
            estimate += max(0.5, self._node_weight(after) * 0.75)
        if before.role != after.role:
            estimate += self._role_cost(before.role, after.role)
        if before.attributes != after.attributes:
            estimate += 0.5
        estimate += abs(
            sum(self._tree_weight(child) for child in before.children)
            - sum(self._tree_weight(child) for child in after.children)
        )
        return min(estimate or self._node_weight(after), delete_and_add)

    def _tree_weight(self, unit: SemanticUnit) -> float:
        return self._node_weight(unit) + sum(
            self._tree_weight(child) for child in unit.children
        )

    def _node_weight(self, unit: SemanticUnit) -> float:
        return self._KIND_WEIGHTS.get(unit.kind, 1.5)

    def _role_cost(self, before: str, after: str) -> float:
        if before in self._CRITICAL_ROLES or after in self._CRITICAL_ROLES:
            return 2.0
        return 0.75

    @staticmethod
    def _paired_path(
        parent: str,
        before: SemanticUnit,
        after: SemanticUnit,
        before_index: int,
        after_index: int,
    ) -> str:
        role = after.role or before.role
        if role:
            return f"{parent}.{role}"
        if before_index == after_index:
            return f"{parent}[{after_index}]"
        return f"{parent}[{before_index}->{after_index}]"

    @staticmethod
    def _child_path(parent: str, child: SemanticUnit, index: int) -> str:
        if child.role:
            return f"{parent}.{child.role}"
        return f"{parent}[{index}]"
