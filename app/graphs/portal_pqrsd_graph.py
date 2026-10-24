from langgraph.graph import StateGraph, END
from app.schemas.graph_state import DocumentState
from app.graphs.nodes.documents_analysis_nodes import (
    analyze_and_route_node,
    markitdown_extractor_node,
    vision_extraction_node,
    unsupported_file_node,
    summarize_and_get_subject_node,
    mega_analysis_node
)
from app.graphs.edges.documents_analysis_edges import (
    route_based_on_file_type,
    route_after_markitdown
)

portal_workflow = StateGraph(DocumentState)

portal_workflow.add_node("analyze_and_route", analyze_and_route_node)
portal_workflow.add_node("markitdown_extract", markitdown_extractor_node)
portal_workflow.add_node("vision_extract", vision_extraction_node)
portal_workflow.add_node("summarize", summarize_and_get_subject_node)
portal_workflow.add_node("mega_analysis", mega_analysis_node)
portal_workflow.add_node("unsupported", unsupported_file_node)

portal_workflow.set_entry_point("analyze_and_route")
portal_workflow.add_conditional_edges(
    "analyze_and_route",
    route_based_on_file_type,
    {
        "pdf_text": "markitdown_extract",
        "office_document": "markitdown_extract",
        "pdf_scanned": "vision_extract",
        "image": "vision_extract",
        "unsupported": "unsupported"
    }
)
portal_workflow.add_conditional_edges(
    "markitdown_extract",
    route_after_markitdown,
    {
        "has_text": "summarize",
        "needs_vision": "vision_extract"
    }
)
portal_workflow.add_edge("vision_extract", "summarize")
portal_workflow.add_edge("summarize", "mega_analysis")
portal_workflow.add_edge("mega_analysis", END)
portal_workflow.add_edge("unsupported", END)

portal_graph = portal_workflow.compile()