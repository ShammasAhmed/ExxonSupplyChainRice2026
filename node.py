"""Network node definition for the caustic soda supply chain model."""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable


class NodeCategory(str, Enum):
    SOURCE = "source"
    SINK = "sink"
    INTERMEDIATE = "intermediate"


class Scenario(str, Enum):
    BEAR = "bear"
    BASE = "base"
    BULL = "bull"


@dataclass(frozen=True, slots=True)
class Node:
    """A location in the supply chain network.

    `name` is the unique identifier and is used as the node key in networkx
    and as the index in gurobipy tupledicts. Pass `node.name` (not the Node
    object) as the key so Gurobi variable names stay readable.

    `coords` is (lat, lon). osmnx/networkx-spatial conventions use x = lon,
    y = lat; the `x`/`y` properties and `to_nx_attrs()` handle that mapping.
    """

    name: str
    city: str
    state: str
    country: str
    category: NodeCategory
    coords: tuple[float, float]  # (lat, lon)
    bear: float
    base: float
    bull: float

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Node name must be non-empty.")

        # Accept plain strings like "sink" and coerce to the enum.
        if not isinstance(self.category, NodeCategory):
            try:
                object.__setattr__(
                    self, "category", NodeCategory(str(self.category).lower())
                )
            except ValueError as exc:
                valid = [c.value for c in NodeCategory]
                raise ValueError(
                    f"Node {self.name!r}: category must be one of {valid}, "
                    f"got {self.category!r}."
                ) from exc

        lat, lon = (float(c) for c in self.coords)
        if not -90.0 <= lat <= 90.0:
            raise ValueError(f"Node {self.name!r}: latitude {lat} out of range.")
        if not -180.0 <= lon <= 180.0:
            raise ValueError(f"Node {self.name!r}: longitude {lon} out of range.")
        object.__setattr__(self, "coords", (lat, lon))

        for s in Scenario:
            v = float(getattr(self, s.value))
            if v < 0:
                raise ValueError(f"Node {self.name!r}: {s.value} value {v} is negative.")
            object.__setattr__(self, s.value, v)

    # --- Geography -------------------------------------------------------
    @property
    def lat(self) -> float:
        return self.coords[0]

    @property
    def lon(self) -> float:
        return self.coords[1]

    @property
    def x(self) -> float:
        """Longitude (osmnx/networkx x-convention)."""
        return self.coords[1]

    @property
    def y(self) -> float:
        """Latitude (osmnx/networkx y-convention)."""
        return self.coords[0]

    # --- Category helpers ------------------------------------------------
    @property
    def is_source(self) -> bool:
        return self.category is NodeCategory.SOURCE

    @property
    def is_sink(self) -> bool:
        return self.category is NodeCategory.SINK

    @property
    def is_intermediate(self) -> bool:
        return self.category is NodeCategory.INTERMEDIATE

    # --- Scenario access -------------------------------------------------
    def value(self, scenario: Scenario | str) -> float:
        """Return the bear/base/bull value for a scenario."""
        return getattr(self, Scenario(scenario).value)

    @property
    def scenarios(self) -> dict[Scenario, float]:
        return {s: self.value(s) for s in Scenario}

    # --- Interop ---------------------------------------------------------
    def to_nx_attrs(self) -> dict[str, Any]:
        """Attribute dict for G.add_node(node.name, **node.to_nx_attrs()).

        Includes x/y so osmnx utilities (e.g. nearest-node lookups, plotting)
        work directly, plus a back-reference to this Node object.
        """
        d = asdict(self)
        d["category"] = self.category.value
        d["x"] = self.x
        d["y"] = self.y
        d["node"] = self
        return d


def add_nodes_to_graph(G, nodes: Iterable[Node]) -> None:
    """Add nodes to a networkx graph keyed by name; rejects duplicate names."""
    for n in nodes:
        if n.name in G:
            raise ValueError(f"Duplicate node name {n.name!r}.")
        G.add_node(n.name, **n.to_nx_attrs())


def nodes_by_category(nodes: Iterable[Node]) -> dict[NodeCategory, list[Node]]:
    out: dict[NodeCategory, list[Node]] = {c: [] for c in NodeCategory}
    for n in nodes:
        out[n.category].append(n)
    return out