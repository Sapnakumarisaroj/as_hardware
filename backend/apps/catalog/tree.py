"""Category tree helpers (Phase 15: up to three levels — department › category › subcategory).

The tree is small (tens to a few hundred rows), so helpers read the `id → parent_id` map in one
query and walk it in Python: portable to every database and no recursive SQL. Callers that need
many lookups in one request pass the map they already loaded (`parent_map()`).
"""

from collections import defaultdict
from collections.abc import Iterable


def parent_map() -> dict[int, int | None]:
    """Every category (deleted ones included, so old references still resolve) → its parent id."""
    from .models import Category

    return dict(Category._base_manager.values_list("id", "parent_id"))


def ancestor_ids(category_id: int | None, parents: dict[int, int | None] | None = None) -> list[int]:
    """`category_id` and everything above it, nearest first. Stops on a cycle (bad data never loops)."""
    parents = parent_map() if parents is None else parents
    chain: list[int] = []
    current = category_id
    while current is not None and current not in chain:
        chain.append(current)
        current = parents.get(current)
    return chain


def level_of(category_id: int | None, *, parent_id: int | None = None) -> int:
    """1 = top level. For an unsaved category, pass its `parent_id`."""
    if category_id is None:
        return 1 if parent_id is None else len(ancestor_ids(parent_id)) + 1
    parents = parent_map()
    if parent_id is not None:
        parents[category_id] = parent_id
    return len(ancestor_ids(category_id, parents))


def children_map(parents: dict[int, int | None] | None = None) -> dict[int | None, list[int]]:
    parents = parent_map() if parents is None else parents
    children: dict[int | None, list[int]] = defaultdict(list)
    for child, parent in parents.items():
        children[parent].append(child)
    return children


def descendant_ids(category_id: int, parents: dict[int, int | None] | None = None) -> set[int]:
    """`category_id` and every category below it."""
    children = children_map(parents)
    found, stack = set(), [category_id]
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.add(current)
        stack.extend(children.get(current, []))
    return found


def subtree_height(category_id: int | None) -> int:
    """Levels below `category_id` (0 = no children)."""
    if category_id is None:
        return 0
    from .models import Category

    children = children_map(dict(Category.objects.values_list("id", "parent_id")))  # deleted ones don't count

    def height(node: int, seen: frozenset) -> int:
        kids = [k for k in children.get(node, []) if k not in seen]
        return 0 if not kids else 1 + max(height(k, seen | {node}) for k in kids)

    return height(category_id, frozenset())


def lineage(category_ids: Iterable[int | None], parents: dict[int, int | None] | None = None) -> frozenset[int]:
    """The given categories plus all their ancestors (for "an offer on Electrical covers Wires")."""
    parents = parent_map() if parents is None else parents
    result: set[int] = set()
    for category_id in category_ids:
        result.update(ancestor_ids(category_id, parents))
    return frozenset(result)


def breadcrumb(category) -> list:
    """Category objects from the top level down to `category`."""
    chain = []
    current = category
    while current is not None and current not in chain:
        chain.append(current)
        current = current.parent
    return list(reversed(chain))
