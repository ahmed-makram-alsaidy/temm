"""What this machine can host right now, so a condition on it is not charged to a route.

The execution gate reported on the provider, the credentials, the workspace and the
PTY, and said nothing about the machine all of them run on. So when the host ran out
of room the failure arrived wearing the only clothes TEMM had for it: the executor
died before a model step, the attempt was classified `executor_local_failure` - which
is true, the failure was local - and the route was withdrawn from selection for half
an hour on the strength of it.

Production evidence 2026-08-21, `attempt-0144bc5d1502`: the CLI aborted in its own
runtime on `MemoryExhaustion` 31 seconds in, exit `0xC0000409`, no events, no tokens,
no diff. That was `opencode/x-preview-f-free`'s fifth recorded failure on the NEXA
project, and the route it condemned was the fleet's only certified one. The route was
never asked. Withdrawing it does not clear the condition either: dispatch moves to the
next route, which dies the same way and is held the same way, so one memory shortage
walks down the catalog withdrawing a route at a time - the same catalog poisoning the
provider-permanence work fixed from the other end.

Two different questions get two different answers here, because conflating them is how
a gate starts refusing hosts that work:

`sufficient` is whether a run can be admitted at all, and it is deliberately hard to
fail. Measured on this host: a run aborted on memory with 0.95 GB physical available,
while another was admitted at 0.77 GB available and ran for over an hour. Available
physical memory therefore does not predict the abort - Windows serves allocations from
the compression store and the page file, neither of which `available` counts - and a
floor on it would have refused the run that worked. What genuinely cannot be served is
an allocation with no room in physical memory *or* the page file, so that, and only
that, disqualifies a host.

`pressure` is whether the host was short at the moment something died, and it decides
nothing about whether to run. It exists so that a local failure has a host reading
beside it instead of a bare classification, and so that the availability hold can
decline to blame a route for a machine-wide condition. Its floor is the level at which
a run has actually been observed to die on this host, and it is only ever read to
*withhold* a penalty: a false positive costs one re-probe of a route that may really be
broken - and it will fail again, and be held, once the host is calm - while a false
negative leaves the behaviour exactly as it is today.

A host that cannot be measured is never reported as a host that failed. `measurable`
is false, `sufficient` stays true, and `pressure` stays false, because absence of
measurement is not evidence, here as everywhere else in the runtime.
"""

from datetime import datetime
from typing import Any, Dict

import psutil

# An allocation with no room in physical memory and none in the page file cannot be
# served, whatever the workload. Sized as a floor on the total of the two rather than
# on physical alone, for the reason in the module docstring, and set low enough that
# it refuses only a host that is genuinely out of room: every run measured on this
# machine, including the ones that aborted, had more than 25 GB of page file free.
COMMIT_FLOOR_BYTES = 256 * 1024 * 1024

# The highest level of available physical memory at which a run has actually been
# observed to abort on this host: 0.95 GB, rounded up to the next whole gigabyte so
# the reading is a boundary rather than a coincidence. Read only to attribute a
# failure, never to refuse a run.
MEMORY_PRESSURE_FLOOR_BYTES = 1024 * 1024 * 1024


def host_capacity() -> Dict[str, Any]:
    """Observe the host, and say what the observation does and does not disqualify."""
    observed_at = datetime.utcnow().isoformat()
    try:
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
    except Exception as exc:  # pragma: no cover - platform specific
        return {
            "measurable": False,
            "sufficient": True,
            "reason": None,
            "pressure": False,
            "pressure_basis": "host_not_measurable",
            "detail": f"Host memory could not be read: {exc}",
            "observed_at": observed_at,
        }
    # A proxy for commit headroom, not the commit limit itself: what physical memory
    # can serve now, plus what the page file can still absorb.
    commit_available = int(memory.available) + int(swap.free)
    sufficient = commit_available >= COMMIT_FLOOR_BYTES
    pressure = int(memory.available) < MEMORY_PRESSURE_FLOOR_BYTES
    return {
        "measurable": True,
        "sufficient": sufficient,
        "reason": None if sufficient else "host_memory_and_pagefile_exhausted",
        "pressure": pressure,
        "pressure_basis": (
            f"available_below_{MEMORY_PRESSURE_FLOOR_BYTES}_bytes_observed_abort_level"
            if pressure else "available_above_observed_abort_level"
        ),
        "detail": (
            f"{commit_available / 1024 ** 3:.2f} GB of combined memory and page file remains, "
            f"below the {COMMIT_FLOOR_BYTES / 1024 ** 3:.2f} GB an allocation needs."
        ) if not sufficient else None,
        "memory_available_bytes": int(memory.available),
        "memory_total_bytes": int(memory.total),
        "memory_percent_used": float(memory.percent),
        "swap_free_bytes": int(swap.free),
        "swap_total_bytes": int(swap.total),
        "commit_available_bytes": commit_available,
        "observed_at": observed_at,
    }


def host_observation() -> Dict[str, Any]:
    """The subset worth carrying on an attempt receipt - bounded, and no secrets."""
    capacity = host_capacity()
    return {
        key: capacity.get(key)
        for key in (
            "measurable", "sufficient", "reason", "pressure", "pressure_basis",
            "memory_available_bytes", "memory_total_bytes", "memory_percent_used",
            "swap_free_bytes", "commit_available_bytes", "observed_at",
        )
    }
