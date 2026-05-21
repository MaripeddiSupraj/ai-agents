from langgraph.graph import StateGraph
from app.models.state import ReviewState, make_initial_state


def placeholder_node(state: ReviewState) -> dict:
    return {"status": "initialized"}


def create_review_graph() -> StateGraph:
    workflow = StateGraph(ReviewState)

    workflow.add_node("initialize", placeholder_node)

    workflow.set_entry_point("initialize")
    workflow.set_finish_point("initialize")

    return workflow.compile()


graph = create_review_graph()
