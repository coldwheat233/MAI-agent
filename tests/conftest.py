"""Shared fixtures for MAI-agent tests."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_dir():
    """Temporary directory that auto-cleans."""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.fixture
def run_context():
    """Basic RunContext with temp cwd."""
    from mai_agent.tools.base import RunContext
    return RunContext(cwd=".")


@pytest.fixture
def registry():
    """Fresh ToolRegistry with all tools loaded."""
    from mai_agent.tools.registry import ToolRegistry
    return ToolRegistry()


@pytest.fixture
def full_registry():
    """Actual global registry with all 26 tools."""
    from mai_agent.tools.registry import registry
    return registry
