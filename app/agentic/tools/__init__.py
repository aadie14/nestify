"""CrewAI-compatible tools for additive agentic workflows."""

from importlib import import_module

_TOOL_MODULES = {
    "CostCalculatorTool": "cost_calculator_tool",
    "DockerRunnerTool": "docker_runner_tool",
    "GraphQueryTool": "graph_query_tool",
    "LoadTesterTool": "load_tester_tool",
    "MetricsCollectorTool": "metrics_collector_tool",
    "PatternMatcherTool": "pattern_matcher_tool",
}


def __getattr__(name: str):
    module_name = _TOOL_MODULES.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    return getattr(module, name)

__all__ = [
    "CostCalculatorTool",
    "DockerRunnerTool",
    "GraphQueryTool",
    "LoadTesterTool",
    "MetricsCollectorTool",
    "PatternMatcherTool",
]
