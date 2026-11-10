"""Measure whole-process peak memory for one candidate in a fresh process.

Results are in bytes and include the Python interpreter and distance preparation.
Use the separate benchmark for timing data.
"""
from dataclasses import asdict
import json
import sys
from time import perf_counter

from picking.algorithms import solve
from picking.distances import Task, prepare_distances
from picking.graph import build_warehouse


def peak_memory_bytes():
    if sys.platform == "win32":
        return windows_peak_working_set_bytes()

    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def windows_peak_working_set_bytes():
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    get_current_process = ctypes.WinDLL("kernel32").GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE

    get_memory_info = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    get_memory_info.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD,
    ]
    get_memory_info.restype = wintypes.BOOL

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not get_memory_info(get_current_process(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: python -m experiments.memory TASKS.jsonl LINE_NUMBER ALGORITHM")
    path, index, algorithm = sys.argv[1:]
    with open(path, encoding="utf-8") as handle:
        task = next(row for i, row in enumerate(handle) if i == int(index))
    task = json.loads(task)
    graph = build_warehouse()
    table = prepare_distances(graph, Task.create(graph, tuple(task['start']), [tuple(p) for p in task['required']]))
    result = solve(table, algorithm, deadline=perf_counter() + 2)
    print(json.dumps({"task_id": task['id'], "algorithm": algorithm, "result": asdict(result),
                      "peak_rss_bytes": peak_memory_bytes(),
                      "scope": "whole process including interpreter and preprocessing"}))


if __name__ == '__main__':
    main()
