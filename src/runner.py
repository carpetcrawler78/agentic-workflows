"""Runner: topologische Sortierung des Workflow-DAG (Kahn's Algorithmus)."""

try:
    from .loader import validate_workflow, validate_workflow_file
except ImportError:
    from loader import validate_workflow, validate_workflow_file


class WorkflowGraphError(Exception):
    """Graph-Fehler jenseits des Schemas (unbekannte Kanten-ID oder Zyklus)."""


class WorkflowCycleError(WorkflowGraphError):
    """Der Graph enthaelt mindestens einen Zyklus."""

    def __init__(self, cycle):
        self.cycle = cycle
        super().__init__(f"Zyklus im Workflow-Graph, beteiligte Knoten: {cycle}")


def topological_order(workflow):
    """Validiert den Workflow (loader.validate_workflow), prueft referenzielle
    Integritaet der edges und gibt die Knoten-IDs in Abhaengigkeitsreihenfolge
    zurueck (Voraussetzung vor Abhaengigem). Wirft WorkflowGraphError bei
    unbekannter Kanten-ID, WorkflowCycleError bei Zyklus."""
    validate_workflow(workflow)

    nodes = workflow["nodes"]
    edges = workflow.get("edges", [])
    node_ids = [node["id"] for node in nodes]
    node_id_set = set(node_ids)
    position = {node_id: idx for idx, node_id in enumerate(node_ids)}

    for edge in edges:
        for end in ("from", "to"):
            if edge[end] not in node_id_set:
                raise WorkflowGraphError(
                    f"Kante verweist auf unbekannte Knoten-ID: {edge[end]}"
                )

    indegree = {node_id: 0 for node_id in node_ids}
    adjacency = {node_id: [] for node_id in node_ids}
    for edge in edges:
        adjacency[edge["from"]].append(edge["to"])
        indegree[edge["to"]] += 1

    # Kahn's Algorithmus: bei mehreren bereiten Knoten (Indegree 0) immer den
    # nehmen, der in nodes[] zuerst steht -- fuer deterministische Reihenfolge.
    ready = [node_id for node_id in node_ids if indegree[node_id] == 0]
    order = []
    while ready:
        ready.sort(key=lambda node_id: position[node_id])
        current = ready.pop(0)
        order.append(current)
        for neighbor in adjacency[current]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                ready.append(neighbor)

    if len(order) != len(node_ids):
        processed = set(order)
        remaining = [node_id for node_id in node_ids if node_id not in processed]
        raise WorkflowCycleError(remaining)

    return order


def topological_order_file(path):
    """Liest+parst (loader.validate_workflow_file) und ruft topological_order."""
    workflow = validate_workflow_file(path)
    return topological_order(workflow)
