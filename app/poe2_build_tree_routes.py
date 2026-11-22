"""Class-aware passive tree paths and edits for the local Buildschmiede planner."""

from collections import deque

from poe2_lexicon import catalogue


SCOPES = ("main", "I", "II", "asc")
WEAPON_SETS = ("I", "II")
ATTRIBUTES_DE = {"Strength": "Stärke", "Dexterity": "Geschick", "Intelligence": "Intelligenz"}


def node_effective_record(ident, setup, data=None):
    """Resolve the actual class variant or attribute elected in a Website build."""
    data = data if data is not None else catalogue()
    geometry = data["plannerTree"]["nodes"].get(ident, {})
    base = data["nodes"].get(ident, {})
    options = setup.get("treeOptions")
    choice = options.get(ident) if isinstance(options, dict) else None
    variant = next((row for row in geometry.get("choices", ()) if str(row["id"]) == str(choice)), None)
    variant = variant or geometry.get("variants", {}).get(setup.get("className"))
    if not variant:
        record = {**base, "atlasIcon": geometry.get("icon", -1)}
        if not record.get("statsDe") and geometry.get("kind") == "attribute" and base.get("stats") == ["+5 to any Attribute"]:
            record["statsDe"] = ["+5 zu einem beliebigen Attribut"]
        return record
    # The base node's translations describe a different effect. Use the alternate
    # record when available, then let display_stats translate any remaining lines.
    localized = data["nodes"].get(str(variant["id"]), {})
    if localized.get("name") != variant["name"]:
        localized = {}
    same_stats = localized.get("stats") == variant.get("stats")
    record = {**base, "name": variant["name"], "de": variant.get("de") or localized.get("de"),
              "aliases": tuple(dict.fromkeys((*variant.get("aliases", ()), *localized.get("aliases", ())))),
              "stats": variant.get("stats", ()),
              "statsDe": variant.get("statsDe") or (localized.get("statsDe", ()) if same_stats else ()),
              "statsHybrid": variant.get("statsHybrid") or (localized.get("statsHybrid", ()) if same_stats else ()),
              "atlasIcon": variant.get("icon", geometry.get("icon", -1))}
    attribute = ATTRIBUTES_DE.get(variant.get("name"))
    if attribute:
        record["de"] = record["de"] or attribute
        if not record["statsDe"] and variant.get("stats") == [f"+5 to {variant['name']}"]:
            record["statsDe"] = [f"+5 zu {attribute}"]
    return record


def _ids(paths, scope):
    return set(map(str, paths.get(scope, ())))


class TreeRoutes:
    def __init__(self, tree, setup, scope):
        self.tree = tree
        self.nodes = tree["nodes"]
        self.setup = setup
        self.scope = scope
        self.paths = setup.get("tree", {})
        self.root = self.root_for(scope)
        self.active = _ids(self.paths, scope)
        self.owned = self.active | ({self.root} if self.root else set())
        if scope in WEAPON_SETS:
            self.owned |= _ids(self.paths, "main")
        self.asc = _ids(self.paths, "asc")
        self.parent = {}
        if self.root in self.nodes:
            self._shortest_routes()

    def root_for(self, scope):
        if scope == "asc":
            return self.tree["ascRoots"].get(self.setup.get("ascendancy"))
        return self.tree["classes"].get(self.setup.get("className"), {}).get("root")

    def available(self, ident):
        row = self.nodes[ident]
        if self.scope == "asc":
            if not row.get("asc") or row["asc"] != self.setup.get("ascendancy"):
                return False
        elif row.get("asc"):
            return False
        if row.get("kind") == "root":
            return ident == self.root
        lock = row.get("lock", {})
        if lock.get("ascendancy") and lock["ascendancy"] != self.setup.get("ascendancy"):
            return False
        if any(str(node) not in self.owned and str(node) not in self.asc for node in lock.get("nodes", ())):
            return False
        if self.scope in WEAPON_SETS and row.get("kind") in {"keystone", "jewel"} and ident not in self.owned:
            return False
        if row.get("isMultipleChoiceOption"):
            for parent in row["links"]:
                if self.nodes[parent].get("isMultipleChoice") and any(
                    other != ident and other in self.owned and self.nodes[other].get("isMultipleChoiceOption")
                    for other in self.nodes[parent]["links"]
                ):
                    return False
        return True

    def _shortest_routes(self):
        # 0–1 BFS minimizes NEW allocations. Starting at the root also prevents
        # disconnected nodes in a quick import from becoming artificial start points.
        queue = deque([self.root])
        distance = {self.root: 0}
        self.parent[self.root] = None
        while queue:
            source = queue.popleft()
            for neighbor in self.nodes[source]["links"]:
                cost = int(neighbor not in self.owned)
                total = distance[source] + cost
                if total >= distance.get(neighbor, float("inf")) or not self.available(neighbor):
                    continue
                distance[neighbor] = total
                self.parent[neighbor] = source
                if cost:
                    queue.append(neighbor)
                else:
                    queue.appendleft(neighbor)

    def route(self, target):
        if target not in self.parent or target in self.owned:
            return ()
        route = []
        node = target
        while node is not None:
            route.append(node)
            node = self.parent[node]
        route.reverse()
        start = next(i for i, node in enumerate(route) if node not in self.owned)
        return tuple(route[max(0, start - 1):])

    def steps(self, target):
        return tuple(node for node in self.route(target) if node not in self.owned)

    def allocate(self, target):
        steps = self.steps(target)
        if not steps or len(self.paths.get(self.scope, ())) + len(steps) > 300:
            return False
        self.paths.setdefault(self.scope, []).extend(steps)
        assigned = set(steps)
        if self.scope == "main":
            for group in WEAPON_SETS:
                if group in self.paths:
                    self.paths[group] = [n for n in self.paths[group] if str(n) not in assigned]
        self._clean_order()
        self.setup["treeOrder"].extend({"group": self.scope, "id": node} for node in steps)
        return True

    def _reachable(self, paths, scope):
        root = self.root_for(scope)
        allowed = _ids(paths, scope)
        if scope in WEAPON_SETS:
            allowed |= _ids(paths, "main")
        reached = {root} if root in self.nodes else set()
        queue = deque(reached)
        while queue:
            for node in self.nodes[queue.popleft()]["links"]:
                if node in allowed and node not in reached:
                    reached.add(node)
                    queue.append(node)
        return reached

    def refunds(self, target):
        """Preview newly disconnected or newly locked allocations in all sets."""
        if target not in self.active or target == self.root:
            return {}
        before = {s: self._reachable(self.paths, s) for s in SCOPES}
        removed = {s: set() for s in SCOPES}
        removed[self.scope].add(target)
        while True:
            paths = {s: _ids(self.paths, s) - removed[s] for s in SCOPES}
            changed = False
            for scope in SCOPES:
                after = self._reachable(paths, scope)
                lost = (before[scope] - after) & paths[scope]
                lost_keys = (before[scope] | self.asc) - (after | paths["asc"])
                for node in paths[scope]:
                    keys = self.nodes.get(node, {}).get("lock", {}).get("nodes", ())
                    if any(str(key) in lost_keys for key in keys):
                        lost.add(node)
                removed[scope].update(lost)
                changed |= bool(lost)
            if not changed:
                return {s: values for s, values in removed.items() if values}

    def refund(self, target):
        removed = self.refunds(target)
        if not removed:
            return False
        for scope, values in removed.items():
            self.paths[scope] = [node for node in self.paths[scope] if str(node) not in values]
        options = self.setup.get("treeOptions")
        if isinstance(options, dict):
            remaining = set().union(*(_ids(self.paths, scope) for scope in SCOPES))
            for node in set().union(*removed.values()) - remaining:
                options.pop(node, None)
        self._clean_order()
        return True

    def _clean_order(self):
        remaining = {scope: _ids(self.paths, scope) for scope in SCOPES}
        order = self.setup.get("treeOrder")
        self.setup["treeOrder"] = [
            entry for entry in (order if isinstance(order, list) else ())
            if isinstance(entry, dict) and isinstance(entry.get("group"), str)
            and str(entry.get("id")) in remaining.get(entry["group"], ())
        ]
