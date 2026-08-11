"""工具基础设施入口"""

from mai_agent.tools.base import Tool, ToolInput, ToolResult, RunContext
from mai_agent.tools.registry import ToolRegistry, registry
from mai_agent.tools.orchestration import run_tools, partition_by_safety

# ── 导入所有内置工具（触发 @registry.register） ──
from mai_agent.tools import file_read    # noqa: F401
from mai_agent.tools import file_write   # noqa: F401
from mai_agent.tools import file_edit    # noqa: F401
from mai_agent.tools import bash         # noqa: F401
from mai_agent.tools import grep         # noqa: F401
from mai_agent.tools import glob         # noqa: F401
from mai_agent.tools import web_search   # noqa: F401
from mai_agent.tools import agent_tool      # noqa: F401
from mai_agent.tools import web_fetch      # noqa: F401
from mai_agent.tools import todo_write     # noqa: F401
from mai_agent.tools import ask_user_question  # noqa: F401
from mai_agent.tools import task_tools     # noqa: F401
from mai_agent.tools import cron_tools     # noqa: F401
from mai_agent.tools import send_message   # noqa: F401
from mai_agent.tools import notebook_edit  # noqa: F401
from mai_agent.tools import feishu_tools  # noqa: F401
from mai_agent.tools import git_tools    # noqa: F401
from mai_agent.tools import skill_tool   # noqa: F401
from mai_agent.tools import worktree_tools  # noqa: F401
from mai_agent.tools import memory_tools # noqa: F401
from mai_agent.tools import mcp_tools   # noqa: F401
from mai_agent.tools import deploy_tools  # noqa: F401
from mai_agent.tools import workflow_tool  # noqa: F401

__all__ = [
    "Tool",
    "ToolInput",
    "ToolResult",
    "RunContext",
    "ToolRegistry",
    "registry",
    "run_tools",
    "partition_by_safety",
]
