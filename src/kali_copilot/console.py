"""Standalone console entry point over the reusable conversation engine."""

from kali_copilot.cockpit import Cockpit as SecurityLlamaConsole
from kali_copilot.cockpit import RequestProgress

__all__ = ["RequestProgress", "SecurityLlamaConsole"]
