"""Storage module to save and load the DependencyGraph as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gh_blast_radius.graph import DependencyGraph
from gh_blast_radius.models import (
    ConsumerEdge,
    InputDef,
    SecretDef,
    WorkflowNode,
    WorkflowRef,
)


def _encode_dataclass(obj: Any) -> Any:
    """Helper to convert dataclasses to dicts for JSON encoding."""
    if isinstance(obj, set):
        return list(obj)
    if hasattr(obj, "__dataclass_fields__"):
        d = asdict(obj)
        d["__type__"] = obj.__class__.__name__
        return d
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _decode_dict(d: dict[str, Any]) -> Any:
    """Helper to reconstruct dataclasses from JSON dicts."""
    obj_type = d.pop("__type__", None)
    if not obj_type:
        return d

    if obj_type == "WorkflowRef":
        return WorkflowRef(**d)
    elif obj_type == "InputDef":
        return InputDef(**d)
    elif obj_type == "SecretDef":
        return SecretDef(**d)
    elif obj_type == "WorkflowNode":
        if isinstance(d.get("ref"), dict):
            d["ref"] = WorkflowRef(**d["ref"])
        return WorkflowNode(**d)
    elif obj_type == "ConsumerEdge":
        if isinstance(d.get("target"), dict):
            d["target"] = WorkflowRef(**d["target"])
        return ConsumerEdge(**d)

    return d


def save_graph(graph: DependencyGraph, path: str | Path) -> None:
    """Save the DependencyGraph to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # We can reconstruct the nx.DiGraph from the lists of producers and edges,
    # or serialize the nx_graph directly. Rebuilding from raw edges is safer.

    # Collect all edges
    all_edges: list[ConsumerEdge] = []
    for _u, _v, data in graph.nx_graph.edges(data=True):
        all_edges.extend(data.get("edges", []))

    # Collect all producers
    producers = list(graph.producers.values())

    data = {
        "version": 1,
        "producers": producers,
        "edges": all_edges,
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, default=_encode_dataclass, indent=2)


def load_graph(path: str | Path) -> DependencyGraph:
    """Load a DependencyGraph from a JSON file."""
    path = Path(path)
    if not path.exists():
        return DependencyGraph()

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f, object_hook=_decode_dict)

    graph = DependencyGraph()

    for producer in data.get("producers", []):
        graph.add_producer(producer)

    for edge in data.get("edges", []):
        graph.add_consumer_edge(edge)

    return graph
