"""Daemon module — background agent execution and supervision."""

from guild.daemon.lifecycle import ExitCode, LifecycleManager
from guild.daemon.resource import (
    ActivityState,
    ResourceMonitor,
    ResourceStatus,
    ResourceThresholds,
    SchedulingMode,
)
from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector, WakeBehavior
from guild.daemon.supervisor import DaemonSupervisor

__all__ = [
    "ActivityState",
    "DaemonSupervisor",
    "ExitCode",
    "LifecycleManager",
    "ResourceMonitor",
    "ResourceStatus",
    "ResourceThresholds",
    "SchedulingMode",
    "SleepWakeConfig",
    "SleepWakeDetector",
    "WakeBehavior",
]

# guild.daemon.run is an entry point module (python -m guild.daemon.run),
# not re-exported here.
