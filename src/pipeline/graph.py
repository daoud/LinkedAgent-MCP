from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.pipeline.nodes.approve import approve_node
from src.pipeline.nodes.dedup import dedup_node
from src.pipeline.nodes.extract import extract_node
from src.pipeline.nodes.finalize import finalize_node
from src.pipeline.nodes.preview import preview_node
from src.pipeline.nodes.publish import publish_node
from src.pipeline.nodes.sanitize import sanitize_node
from src.pipeline.nodes.schedule import schedule_node
from src.pipeline.nodes.transform import transform_node
from src.pipeline.nodes.validate import validate_node
from src.pipeline.state import PipelineState


# ---- routing helpers -------------------------------------------------------

def _route_dedup(state: PipelineState) -> str:
    return "finalize" if state.get("error") else "sanitize"


def _route_sanitize(state: PipelineState) -> str:
    return "finalize" if not state.get("is_safe", True) else "transform"


def _route_validate(state: PipelineState) -> str:
    return "finalize" if not state.get("validation_passed", True) else "schedule"


def _route_schedule(state: PipelineState) -> str:
    from src.config import get_settings  # avoid circular at module load

    return "approve" if get_settings().approval_required else "preview"


def _route_approve(state: PipelineState) -> str:
    status = state.get("approval_status", "approved")
    return "finalize" if status in ("rejected", "timeout") else "preview"


# ---- graph factory ---------------------------------------------------------

def build_graph(checkpointer=None):
    """Build and compile the LangGraph pipeline.

    Pass a checkpointer (AsyncPostgresSaver) to enable pause/resume for human
    approval. Omit for stateless, single-shot runs (tests, dry-runs).
    """
    g = StateGraph(PipelineState)

    g.add_node("extract", extract_node)
    g.add_node("dedup", dedup_node)
    g.add_node("sanitize", sanitize_node)
    g.add_node("transform", transform_node)
    g.add_node("validate", validate_node)
    g.add_node("schedule", schedule_node)
    g.add_node("approve", approve_node)
    g.add_node("preview", preview_node)
    g.add_node("publish", publish_node)
    g.add_node("finalize", finalize_node)

    g.set_entry_point("extract")

    g.add_edge("extract", "dedup")
    g.add_conditional_edges("dedup", _route_dedup, {"sanitize": "sanitize", "finalize": "finalize"})
    g.add_conditional_edges("sanitize", _route_sanitize, {"transform": "transform", "finalize": "finalize"})
    g.add_edge("transform", "validate")
    g.add_conditional_edges("validate", _route_validate, {"schedule": "schedule", "finalize": "finalize"})
    g.add_conditional_edges("schedule", _route_schedule, {"approve": "approve", "preview": "preview"})
    g.add_conditional_edges("approve", _route_approve, {"preview": "preview", "finalize": "finalize"})
    g.add_edge("preview", "publish")
    g.add_edge("publish", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)
