from __future__ import annotations

from app.graph.state import GraphState


class NovelWorkflow:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self._compiled = None

    def invoke(self, state: GraphState) -> GraphState:
        try:
            graph = self._graph()
        except Exception:
            return self._invoke_fallback(state)
        return graph.invoke(state)

    def _graph(self):
        if self._compiled is not None:
            return self._compiled
        from langgraph.graph import END, START, StateGraph

        from app.graph.nodes import (
            check_node,
            checkpoint_node,
            commit_node,
            draft_node,
            extract_node,
            finish_node,
            load_context_node,
            plan_node,
            review_node,
            rewrite_node,
            route_after_checkpoint,
            route_after_review,
        )

        graph = StateGraph(GraphState)
        graph.add_node("load_context", load_context_node(self.runtime))
        graph.add_node("plan", plan_node(self.runtime))
        graph.add_node("draft", draft_node(self.runtime))
        graph.add_node("extract", extract_node(self.runtime))
        graph.add_node("check", check_node(self.runtime))
        graph.add_node("review", review_node(self.runtime))
        graph.add_node("rewrite", rewrite_node(self.runtime))
        graph.add_node("commit", commit_node(self.runtime))
        graph.add_node("checkpoint", checkpoint_node(self.runtime))
        graph.add_node("finish", finish_node(self.runtime))
        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "plan")
        graph.add_edge("plan", "draft")
        graph.add_edge("draft", "extract")
        graph.add_edge("extract", "check")
        graph.add_edge("check", "review")
        graph.add_conditional_edges("review", route_after_review, {"rewrite": "rewrite", "commit": "commit"})
        graph.add_edge("rewrite", "extract")
        graph.add_edge("commit", "checkpoint")
        graph.add_conditional_edges("checkpoint", route_after_checkpoint, {"load_context": "load_context", "finish": "finish"})
        graph.add_edge("finish", END)
        self._compiled = graph.compile()
        return self._compiled

    def _invoke_fallback(self, state: GraphState) -> GraphState:
        from app.graph.nodes import (
            check_node,
            checkpoint_node,
            commit_node,
            draft_node,
            extract_node,
            finish_node,
            load_context_node,
            plan_node,
            review_node,
            rewrite_node,
        )

        steps = {
            "load_context": load_context_node(self.runtime),
            "plan": plan_node(self.runtime),
            "draft": draft_node(self.runtime),
            "extract": extract_node(self.runtime),
            "check": check_node(self.runtime),
            "review": review_node(self.runtime),
            "rewrite": rewrite_node(self.runtime),
            "commit": commit_node(self.runtime),
            "checkpoint": checkpoint_node(self.runtime),
            "finish": finish_node(self.runtime),
        }
        action = "load_context"
        guard = 0
        while action != "finish" and guard < 100:
            guard += 1
            state = steps[action](state)
            if action == "review":
                action = "rewrite" if state.get("next_action") == "rewrite" else "commit"
            elif action == "checkpoint":
                action = "load_context" if state.get("next_action") == "continue" else "finish"
            else:
                action = {
                    "load_context": "plan",
                    "plan": "draft",
                    "draft": "extract",
                    "extract": "check",
                    "check": "review",
                    "rewrite": "extract",
                    "commit": "checkpoint",
                }[action]
        state = steps["finish"](state)
        return state
