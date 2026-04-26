#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HOST = os.environ.get("TINY_M73_DASH_HOST", "127.0.0.1")
PORT = int(os.environ.get("TINY_M73_DASH_PORT", "8766"))
REMOTE_HOST = "192.168.1.175"
REMOTE_NAME = "tiny-m73"
POLL_INTERVAL_SECONDS = 30
HARDWARE_TTL_SECONDS = 3600
STORAGE_TTL_SECONDS = 600
PAYLOAD_CACHE_TTL_SECONDS = int(os.environ.get("TINY_M73_PAYLOAD_CACHE_TTL_SECONDS", "5"))
MAX_PAYLOAD_SERIES_SAMPLES = int(os.environ.get("TINY_M73_MAX_PAYLOAD_SERIES_SAMPLES", "1440"))
LOCAL_STATE_DIR = Path(__file__).resolve().parents[1] / ".local"
PRIMARY_QUEUE_LOCK_NAME = os.environ.get("TINY_M73_QUEUE_LOCK_NAME", "runner-host")
PRIMARY_QUEUE_CAPACITY = int(os.environ.get("TINY_M73_QUEUE_CAPACITY", "4"))
PRIMARY_QUEUE_SLOT_SECONDS = int(os.environ.get("TINY_M73_QUEUE_SLOT_SECONDS", "600"))
PRIMARY_QUEUE_WAIT_STALE_SECONDS = int(os.environ.get("TINY_M73_QUEUE_WAIT_STALE_SECONDS", "180"))
PRIMARY_QUEUE_HOLDER_STALE_SECONDS = int(os.environ.get("TINY_M73_QUEUE_HOLDER_STALE_SECONDS", "7200"))
HISTORY_FILE = LOCAL_STATE_DIR / "tiny-m73_sys_history_v5.csv"
LEGACY_HISTORY_FILES = [
    LOCAL_STATE_DIR / "tiny-m73_sys_history_v4.csv",
    LOCAL_STATE_DIR / "tiny-m73_sys_history_v3.csv",
    LOCAL_STATE_DIR / "tiny-m73_sys_history_v2.csv",
]


REMOTE_DYNAMIC_SCRIPT = r"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
from datetime import datetime


def read_text(path):
    try:
        return pathlib.Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def read_json(path):
    raw = read_text(path)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def parse_iso_epoch(value):
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def meminfo():
    data = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, value = line.split(":", 1)
            data[key] = int(value.strip().split()[0])
    return data


def cpu_stats():
    total_stats = None
    core_stats = {}
    with open("/proc/stat", "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            if name != "cpu" and not (name.startswith("cpu") and name[3:].isdigit()):
                continue
            values = [int(value) for value in parts[1:]]
            total = sum(values)
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            entry = {"total": total, "idle": idle}
            if name == "cpu":
                total_stats = entry
            else:
                core_stats[name] = entry
    return total_stats, core_stats


def disk_usage():
    fs = os.statvfs("/")
    total = fs.f_frsize * fs.f_blocks
    avail = fs.f_frsize * fs.f_bavail
    used = total - avail
    used_pct = (used / total * 100.0) if total else 0.0
    return total, used, avail, used_pct


def network_totals():
    rx_total = 0
    tx_total = 0
    exclude = ("lo", "docker", "veth", "br-", "virbr", "tun", "tap")
    with open("/proc/net/dev", "r", encoding="utf-8") as handle:
        for line in handle.readlines()[2:]:
            iface, payload = line.split(":", 1)
            iface = iface.strip()
            if not iface or iface.startswith(exclude):
                continue
            fields = payload.split()
            rx_total += int(fields[0])
            tx_total += int(fields[8])
    return rx_total, tx_total


def root_disk_device():
    try:
        source = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", "/"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        source = ""
    if not source:
        return ""
    source_name = pathlib.Path(source).name
    try:
        parent = subprocess.run(
            ["lsblk", "-no", "PKNAME", source],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        parent = ""
    return parent or source_name


def disk_stats(device):
    if not device:
        return {}
    try:
        with open("/proc/diskstats", "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 14 or parts[2] != device:
                    continue
                return {
                    "device": device,
                    "read_ios": int(parts[3]),
                    "read_sectors": int(parts[5]),
                    "read_ms": int(parts[6]),
                    "write_ios": int(parts[7]),
                    "write_sectors": int(parts[9]),
                    "write_ms": int(parts[10]),
                    "io_ms": int(parts[12]),
                    "weighted_io_ms": int(parts[13]),
                }
    except Exception:
        return {}
    return {}


def shorten_runner_name(name, head=18, tail=8):
    if len(name) <= head + tail + 1:
        return name
    return name[:head] + "..." + name[-tail:]


def active_runners():
    try:
        output = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        return []

    rows = {}
    run_pattern = re.compile(r"/home/joe/(pm99-runner(?:-codex-b)?)/workspace/runs/([^/ ]+)")
    namespace_pattern = re.compile(r"/home/joe/pm99-runner/namespaces/([^/ ]+)")
    driver_pattern = re.compile(r"/workspace/repo/scripts/pm99_runner/([^ /]+)")
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid_raw, args = parts
        runner_process = (
            "/usr/local/bin/pm99-runner-entrypoint" in args
            or "/workspace/repo/scripts/pm99_runner/" in args
        )
        runner_launcher = (
            ("docker run" in args or "docker create" in args)
            and "/workspace/repo/scripts/pm99_runner/" in args
        )
        if not (runner_process or runner_launcher):
            continue
        try:
            pid = int(pid_raw)
        except ValueError:
            continue

        driver_match = driver_pattern.search(args)
        driver = pathlib.Path(driver_match.group(1)).name if driver_match else ""

        matches = []
        for root, run_name in run_pattern.findall(args):
            root_label = "codex-b" if root.endswith("-codex-b") else "runner"
            label = "%s/%s" % (root_label, shorten_runner_name(run_name))
            path = "/home/joe/%s/workspace/runs/%s" % (root, run_name)
            matches.append((label, root_label, "run", run_name, path))

        for namespace_name in namespace_pattern.findall(args):
            label = "ns/%s" % shorten_runner_name(namespace_name)
            path = "/home/joe/pm99-runner/namespaces/%s" % namespace_name
            matches.append((label, "runner", "namespace", namespace_name, path))

        for label, root_label, kind, name, path in matches:
            row = rows.setdefault(
                label,
                {
                    "label": label,
                    "root": root_label,
                    "kind": kind,
                    "name": name,
                    "path": path,
                    "driver": driver,
                    "pids": set(),
                },
            )
            if driver and not row["driver"]:
                row["driver"] = driver
            row["pids"].add(pid)

    result = []
    for row in rows.values():
        result.append(
            {
                "label": row["label"],
                "root": row["root"],
                "kind": row["kind"],
                "name": row["name"],
                "path": row["path"],
                "driver": row["driver"],
                "pid_count": len(row["pids"]),
            }
        )
    result.sort(key=lambda item: (item["root"], item["label"]))
    return result


def queue_state():
    queue_root = pathlib.Path("/home/joe/pm99-runner/shared/queues")
    lock_root = pathlib.Path("/home/joe/pm99-runner/shared/locks")
    now_epoch = int(datetime.now().timestamp())

    def read_epoch(path):
        raw = read_text(path)
        if not raw:
            return 0
        try:
            return int(raw)
        except Exception:
            return 0

    def owner_pid(path):
        raw = read_text(path / "owner.pid")
        try:
            return int(raw)
        except Exception:
            return 0

    def wait_entry(entry, position):
        created_epoch = read_epoch(entry / "created.epoch") or int(entry.stat().st_mtime)
        heartbeat_epoch = read_epoch(entry / "heartbeat.epoch") or int(entry.stat().st_mtime)
        return {
            "ticket": entry.name,
            "owner": read_text(entry / "owner.txt") or "unknown",
            "host": read_text(entry / "owner.host") or "",
            "pid": owner_pid(entry),
            "reason": read_text(entry / "reason.txt") or "unknown",
            "position": position,
            "created_epoch": created_epoch,
            "heartbeat_epoch": heartbeat_epoch,
            "age_seconds": max(0, now_epoch - created_epoch),
            "heartbeat_age_seconds": max(0, now_epoch - heartbeat_epoch),
        }

    def holder_entry(entry, ticket, kind):
        heartbeat_epoch = read_epoch(entry / "heartbeat.epoch") or int(entry.stat().st_mtime)
        return {
            "ticket": ticket,
            "kind": kind,
            "owner": read_text(entry / "owner.txt") or "unknown",
            "host": read_text(entry / "owner.host") or "",
            "pid": owner_pid(entry),
            "reason": read_text(entry / "reason.txt") or "unknown",
            "heartbeat_epoch": heartbeat_epoch,
            "age_seconds": max(0, now_epoch - heartbeat_epoch),
        }

    lock_names = set()
    if lock_root.exists():
        for child in lock_root.iterdir():
            if not child.is_dir():
                continue
            if child.name.endswith(".slots"):
                lock_names.add(child.name[:-6])
            else:
                lock_names.add(child.name)
    if queue_root.exists():
        for child in queue_root.iterdir():
            if child.is_dir():
                lock_names.add(child.name)

    domains = {}
    for lock_name in sorted(lock_names):
        holders = []
        legacy_dir = lock_root / lock_name
        if legacy_dir.is_dir():
            holders.append(holder_entry(legacy_dir, lock_name, "legacy"))

        slots_dir = lock_root / f"{lock_name}.slots"
        if slots_dir.is_dir():
            for slot_dir in sorted(child for child in slots_dir.iterdir() if child.is_dir()):
                holders.append(holder_entry(slot_dir, slot_dir.name, "slot"))

        waiters = []
        domain_queue_dir = queue_root / lock_name
        if domain_queue_dir.is_dir():
            queue_entries = sorted(child for child in domain_queue_dir.iterdir() if child.is_dir())
            for idx, entry in enumerate(queue_entries, start=1):
                waiters.append(wait_entry(entry, idx))

        domains[lock_name] = {
            "lock_name": lock_name,
            "holders": holders,
            "waiters": waiters,
            "active_holders": len(holders),
            "queue_depth": len(waiters),
        }

    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "lock_domains": sorted(domains.keys()),
        "domains": domains,
    }


def worker_state():
    workers_root = pathlib.Path("/home/joe/pm99-runner/shared/workers")
    now_epoch = int(datetime.now().timestamp())

    def container_running(container_name):
        if not container_name:
            return None
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip().lower()
        except Exception:
            return None
        if result in {"true", "1", "yes"}:
            return True
        if result in {"false", "0", "no"}:
            return False
        return None

    workers = []
    total_lanes = 0
    active_lanes = 0
    if workers_root.is_dir():
        for worker_dir in sorted(child for child in workers_root.iterdir() if child.is_dir()):
            lanes = []
            lanes_root = worker_dir / "lanes"
            if lanes_root.is_dir():
                for lane_dir in sorted(child for child in lanes_root.iterdir() if child.is_dir()):
                    lease_payload = read_json(lane_dir / "lease.json") or {}
                    started_epoch = parse_iso_epoch(lease_payload.get("started_at"))
                    heartbeat_epoch = parse_iso_epoch(lease_payload.get("heartbeat_at"))
                    lease_active = bool(lease_payload)
                    container_name = str(lease_payload.get("container_name") or "")
                    container_state = container_running(container_name)
                    if container_state is False:
                        active = False
                        status = "completed"
                    else:
                        active = lease_active
                        status = str(lease_payload.get("status") or ("idle" if not active else "running"))
                    lane_payload = {
                        "worker": worker_dir.name,
                        "lane": lane_dir.name,
                        "label": f"{worker_dir.name}/{lane_dir.name}",
                        "active": active,
                        "status": status,
                        "run_tag": str(lease_payload.get("run_tag") or ""),
                        "owner": str(lease_payload.get("owner") or ""),
                        "launcher": str(lease_payload.get("launcher") or ""),
                        "container_name": container_name,
                        "container_running": container_state,
                        "display": str(lease_payload.get("display") or ""),
                        "artifacts_dir": str(lease_payload.get("artifacts_dir") or ""),
                        "started_at": str(lease_payload.get("started_at") or ""),
                        "heartbeat_at": str(lease_payload.get("heartbeat_at") or ""),
                        "age_seconds": max(0, now_epoch - started_epoch) if started_epoch else 0,
                        "heartbeat_age_seconds": max(0, now_epoch - heartbeat_epoch) if heartbeat_epoch else 0,
                    }
                    lanes.append(lane_payload)
            lane_count = len(lanes)
            worker_active = sum(1 for lane in lanes if lane.get("active"))
            total_lanes += lane_count
            active_lanes += worker_active
            workers.append(
                {
                    "name": worker_dir.name,
                    "lane_count": lane_count,
                    "active_lanes": worker_active,
                    "idle_lanes": max(0, lane_count - worker_active),
                    "lanes": lanes,
                }
            )
    workers.sort(key=lambda item: (-item["active_lanes"], item["name"]))
    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "worker_count": len(workers),
        "total_lanes": total_lanes,
        "active_lanes": active_lanes,
        "workers": workers,
    }

def thermal_from_hwmon():
    entries = []
    for hwmon in sorted(pathlib.Path("/sys/class/hwmon").glob("hwmon*")):
        source = read_text(hwmon / "name") or hwmon.name
        labeled = False
        for label_path in sorted(hwmon.glob("temp*_label")):
            labeled = True
            number = label_path.name[len("temp") : -len("_label")]
            input_path = hwmon / ("temp%s_input" % number)
            label = read_text(label_path)
            raw = read_text(input_path)
            if not raw:
                continue
            label_lower = label.lower()
            kind = "sensor"
            if label.startswith("Core "):
                kind = "core"
            elif "package" in label_lower or "tdie" in label_lower:
                kind = "package"
            entries.append(
                {
                    "label": label or ("%s temp%s" % (source, number)),
                    "temp_c": round(int(raw) / 1000.0, 1),
                    "kind": kind,
                    "source": source,
                }
            )
        if labeled:
            continue
        for input_path in sorted(hwmon.glob("temp*_input")):
            raw = read_text(input_path)
            if not raw:
                continue
            label = "%s %s" % (source, input_path.stem)
            entries.append(
                {
                    "label": label,
                    "temp_c": round(int(raw) / 1000.0, 1),
                    "kind": "sensor",
                    "source": source,
                }
            )
    return entries


def thermal_from_zones():
    entries = []
    counts = {}
    for zone in sorted(pathlib.Path("/sys/class/thermal").glob("thermal_zone*")):
        kind = read_text(zone / "type")
        raw = read_text(zone / "temp")
        if not kind or not raw:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        label = kind if counts[kind] == 1 else "%s #%d" % (kind, counts[kind])
        entry_kind = "package" if kind == "x86_pkg_temp" else "zone"
        entries.append(
            {
                "label": label,
                "temp_c": round(int(raw) / 1000.0, 1),
                "kind": entry_kind,
                "source": zone.name,
            }
        )
    return entries


def thermal_sensors():
    entries = thermal_from_hwmon()
    if not entries:
        return thermal_from_zones()
    if not any(entry["kind"] == "package" for entry in entries):
        for zone_entry in thermal_from_zones():
            if zone_entry["kind"] == "package":
                entries.append(zone_entry)
                break
    return entries


def package_temp(entries):
    for entry in entries:
        if entry["kind"] == "package":
            return entry["temp_c"]
    return entries[0]["temp_c"] if entries else None

def top_processes():
    cpu_map = {}
    try:
        output = subprocess.run(
            ["ps", "-eo", "pid=,pcpu=,comm="],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        output = ""
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        pid, cpu_pct, comm = parts
        try:
            cpu_map[pid] = {"cpu_pct": float(cpu_pct), "comm": comm}
        except ValueError:
            continue

    rows = []
    for status in pathlib.Path("/proc").glob("[0-9]*/status"):
        pid = status.parent.name
        try:
            lines = status.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        data = {}
        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            data[key] = value.strip()
        rss_kb = int((data.get("VmRSS", "0 kB").split() or ["0"])[0])
        swap_kb = int((data.get("VmSwap", "0 kB").split() or ["0"])[0])
        if rss_kb <= 0 and swap_kb <= 0:
            continue
        cpu_pct = cpu_map.get(pid, {}).get("cpu_pct", 0.0)
        score = swap_kb * 2 + rss_kb + int(cpu_pct * 1024.0)
        rows.append(
            (
                score,
                {
                    "pid": int(pid),
                    "name": data.get("Name", cpu_map.get(pid, {}).get("comm", "?")),
                    "cpu_pct": round(cpu_pct, 1),
                    "rss_mib": round(rss_kb / 1024.0, 1),
                    "swap_mib": round(swap_kb / 1024.0, 1),
                },
            )
        )
    rows.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in rows[:10]]


def users():
    try:
        output = subprocess.run(["who"], check=True, capture_output=True, text=True).stdout
    except Exception:
        return 0
    return len([line for line in output.splitlines() if line.strip()])


loadavg = pathlib.Path("/proc/loadavg").read_text(encoding="utf-8").split()
load1, load5, load15 = (float(loadavg[index]) for index in range(3))
running_processes, total_processes = (int(value) for value in loadavg[3].split("/", 1))
mem = meminfo()
total_stats, core_stats = cpu_stats()
disk_total, disk_used, disk_avail, disk_used_pct = disk_usage()
root_disk = root_disk_device()
rx_total, tx_total = network_totals()
uptime_secs = float(pathlib.Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
thermal = thermal_sensors()

payload = {
    "timestamp": datetime.now().astimezone().isoformat(),
    "cpu_total_jiffies": total_stats["total"],
    "cpu_idle_jiffies": total_stats["idle"],
    "cpu_count": os.cpu_count() or len(core_stats) or 1,
    "core_stats": core_stats,
    "thermal_sensors": thermal,
    "temp_c": package_temp(thermal),
    "load1": load1,
    "load5": load5,
    "load15": load15,
    "mem_total_kb": mem.get("MemTotal", 0),
    "mem_available_kb": mem.get("MemAvailable", 0),
    "swap_total_kb": mem.get("SwapTotal", 0),
    "swap_free_kb": mem.get("SwapFree", 0),
    "disk_total_bytes": disk_total,
    "disk_used_bytes": disk_used,
    "disk_avail_bytes": disk_avail,
    "disk_used_pct": round(disk_used_pct, 1),
    "disk_stats": disk_stats(root_disk),
    "rx_bytes_total": rx_total,
    "tx_bytes_total": tx_total,
    "uptime_secs": uptime_secs,
    "users": users(),
    "running_processes": running_processes,
    "total_processes": total_processes,
    "top_processes": top_processes(),
    "active_runners": active_runners(),
    "queue_state": queue_state(),
    "worker_state": worker_state(),
}
print(json.dumps(payload))
"""


REMOTE_HARDWARE_SCRIPT = r"""
from __future__ import annotations

import json
import pathlib
import platform
import subprocess


def command_output(args):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def lscpu_map():
    output = command_output(["lscpu"])
    data = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def meminfo():
    data = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, value = line.split(":", 1)
            data[key] = int(value.strip().split()[0])
    return data


def dmi(name):
    path = pathlib.Path("/sys/class/dmi/id") / name
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def first_disk():
    output = command_output(["lsblk", "-J", "-dn", "-o", "NAME,TYPE,SIZE,MODEL,SERIAL"])
    if not output:
        return {}
    try:
        parsed = json.loads(output)
    except Exception:
        return {}
    for device in parsed.get("blockdevices", []):
        if device.get("type") == "disk":
            return device
    return {}


cpu = lscpu_map()
mem = meminfo()
disk = first_disk()

payload = {
    "hostname": platform.node(),
    "architecture": platform.machine(),
    "kernel": command_output(["uname", "-srmo"]),
    "vendor_id": cpu.get("Vendor ID", ""),
    "cpu_model": cpu.get("Model name", ""),
    "cpu_count": cpu.get("CPU(s)", ""),
    "cores_per_socket": cpu.get("Core(s) per socket", ""),
    "threads_per_core": cpu.get("Thread(s) per core", ""),
    "socket_count": cpu.get("Socket(s)", ""),
    "cpu_max_mhz": cpu.get("CPU max MHz", ""),
    "cpu_min_mhz": cpu.get("CPU min MHz", ""),
    "memory_total_gb": round(mem.get("MemTotal", 0) / 1024.0 / 1024.0, 1),
    "swap_total_gb": round(mem.get("SwapTotal", 0) / 1024.0 / 1024.0, 1),
    "system_vendor": dmi("sys_vendor"),
    "product_name": dmi("product_name"),
    "product_version": dmi("product_version"),
    "board_vendor": dmi("board_vendor"),
    "board_name": dmi("board_name"),
    "bios_vendor": dmi("bios_vendor"),
    "bios_version": dmi("bios_version"),
    "disk_name": disk.get("name", ""),
    "disk_size": disk.get("size", ""),
    "disk_model": disk.get("model", ""),
    "disk_serial": disk.get("serial", ""),
    "ip_addresses": command_output(["hostname", "-I"]),
}
print(json.dumps(payload))
"""


REMOTE_STORAGE_SCRIPT = r"""
from __future__ import annotations

import json
import pathlib
import subprocess
from datetime import datetime


def du_map(paths):
    paths = [path for path in paths if pathlib.Path(path).exists()]
    if not paths:
        return {}
    try:
        output = subprocess.run(
            ["du", "-sxB1", *paths],
            check=False,
            stdout=subprocess.PIPE,
            text=True,
            stderr=subprocess.DEVNULL,
        ).stdout.strip()
    except Exception:
        return {}
    mapping = {}
    for line in output.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        size_raw, path = parts
        try:
            mapping[path] = int(size_raw)
        except Exception:
            continue
    return mapping


def gib(value):
    return round(value / 1024.0 / 1024.0 / 1024.0, 1)


targets = [
    ("var", "/var", "/var"),
    ("tmp", "/tmp", "/tmp"),
    ("runner", "/home/joe/pm99-runner", "pm99-runner"),
    ("runner_namespaces", "/home/joe/pm99-runner/namespaces", "runner namespaces"),
    ("runner_workspace", "/home/joe/pm99-runner/workspace", "runner workspace"),
    ("runner_codex_b", "/home/joe/pm99-runner-codex-b", "pm99-runner-codex-b"),
    ("picoclaw", "/home/joe/picoclaw-home", "picoclaw-home"),
    ("openclaw_migration", "/home/joe/openclaw-migration", "openclaw-migration"),
]

target_sizes = du_map([path for _, path, _ in targets])
directories = []
for key, path, label in targets:
    directories.append(
        {
            "id": key,
            "label": label,
            "path": path,
            "size_gb": gib(target_sizes.get(path, 0)),
        }
    )

namespaces = []
root = pathlib.Path("/home/joe/pm99-runner/namespaces")
children = [str(child) for child in root.iterdir() if child.is_dir()] if root.exists() else []
child_sizes = du_map(children)
for child in children:
    name = pathlib.Path(child).name
    namespaces.append(
        {
            "name": name,
            "path": child,
            "size_gb": gib(child_sizes.get(child, 0)),
        }
    )
namespaces.sort(key=lambda item: item["size_gb"], reverse=True)

payload = {
    "timestamp": datetime.now().astimezone().isoformat(),
    "directories": directories,
    "namespaces": namespaces[:8],
}
print(json.dumps(payload))
"""


@dataclass
class RawSample:
    timestamp: str
    cpu_total_jiffies: int
    cpu_idle_jiffies: int
    cpu_count: int
    core_stats_json: str
    thermal_sensors_json: str
    top_processes_json: str
    disk_stats_json: str
    active_runners_json: str
    worker_state_json: str
    queue_state_json: str
    temp_c: float | None
    load1: float
    load5: float
    load15: float
    mem_total_kb: int
    mem_available_kb: int
    swap_total_kb: int
    swap_free_kb: int
    disk_total_bytes: int
    disk_used_bytes: int
    disk_avail_bytes: int
    disk_used_pct: float
    rx_bytes_total: int
    tx_bytes_total: int
    uptime_secs: float
    users: int
    running_processes: int
    total_processes: int

    @staticmethod
    def fieldnames() -> list[str]:
        return [
            "timestamp",
            "cpu_total_jiffies",
            "cpu_idle_jiffies",
            "cpu_count",
            "core_stats_json",
            "thermal_sensors_json",
            "top_processes_json",
            "disk_stats_json",
            "active_runners_json",
            "worker_state_json",
            "queue_state_json",
            "temp_c",
            "load1",
            "load5",
            "load15",
            "mem_total_kb",
            "mem_available_kb",
            "swap_total_kb",
            "swap_free_kb",
            "disk_total_bytes",
            "disk_used_bytes",
            "disk_avail_bytes",
            "disk_used_pct",
            "rx_bytes_total",
            "tx_bytes_total",
            "uptime_secs",
            "users",
            "running_processes",
            "total_processes",
        ]

    def to_row(self) -> dict[str, str]:
        return {
            "timestamp": self.timestamp,
            "cpu_total_jiffies": str(self.cpu_total_jiffies),
            "cpu_idle_jiffies": str(self.cpu_idle_jiffies),
            "cpu_count": str(self.cpu_count),
            "core_stats_json": self.core_stats_json,
            "thermal_sensors_json": self.thermal_sensors_json,
            "top_processes_json": self.top_processes_json,
            "disk_stats_json": self.disk_stats_json,
            "active_runners_json": self.active_runners_json,
            "worker_state_json": self.worker_state_json,
            "queue_state_json": self.queue_state_json,
            "temp_c": "" if self.temp_c is None else f"{self.temp_c:.1f}",
            "load1": f"{self.load1:.2f}",
            "load5": f"{self.load5:.2f}",
            "load15": f"{self.load15:.2f}",
            "mem_total_kb": str(self.mem_total_kb),
            "mem_available_kb": str(self.mem_available_kb),
            "swap_total_kb": str(self.swap_total_kb),
            "swap_free_kb": str(self.swap_free_kb),
            "disk_total_bytes": str(self.disk_total_bytes),
            "disk_used_bytes": str(self.disk_used_bytes),
            "disk_avail_bytes": str(self.disk_avail_bytes),
            "disk_used_pct": f"{self.disk_used_pct:.1f}",
            "rx_bytes_total": str(self.rx_bytes_total),
            "tx_bytes_total": str(self.tx_bytes_total),
            "uptime_secs": f"{self.uptime_secs:.1f}",
            "users": str(self.users),
            "running_processes": str(self.running_processes),
            "total_processes": str(self.total_processes),
        }

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "RawSample":
        temp_raw = (row.get("temp_c") or "").strip()
        return cls(
            timestamp=row["timestamp"],
            cpu_total_jiffies=int(row["cpu_total_jiffies"]),
            cpu_idle_jiffies=int(row["cpu_idle_jiffies"]),
            cpu_count=int(row["cpu_count"]),
            core_stats_json=row.get("core_stats_json", "{}"),
            thermal_sensors_json=row.get("thermal_sensors_json", "[]"),
            top_processes_json=row.get("top_processes_json", "[]"),
            disk_stats_json=row.get("disk_stats_json", "{}"),
            active_runners_json=row.get("active_runners_json", "[]"),
            worker_state_json=row.get("worker_state_json", "{}"),
            queue_state_json=row.get("queue_state_json", "{}"),
            temp_c=float(temp_raw) if temp_raw else None,
            load1=float(row["load1"]),
            load5=float(row["load5"]),
            load15=float(row["load15"]),
            mem_total_kb=int(row["mem_total_kb"]),
            mem_available_kb=int(row["mem_available_kb"]),
            swap_total_kb=int(row["swap_total_kb"]),
            swap_free_kb=int(row["swap_free_kb"]),
            disk_total_bytes=int(row["disk_total_bytes"]),
            disk_used_bytes=int(row["disk_used_bytes"]),
            disk_avail_bytes=int(row["disk_avail_bytes"]),
            disk_used_pct=float(row["disk_used_pct"]),
            rx_bytes_total=int(row["rx_bytes_total"]),
            tx_bytes_total=int(row["tx_bytes_total"]),
            uptime_secs=float(row["uptime_secs"]),
            users=int(row["users"]),
            running_processes=int(row["running_processes"]),
            total_processes=int(row["total_processes"]),
        )


class HistoryStore:
    def __init__(self, history_file: Path) -> None:
        self.history_file = history_file
        self._lock = threading.Lock()
        self._samples = self._load_samples()
        self._last_poll_monotonic = time.monotonic()
        self._last_error: str | None = None

    def _read_history_file(self, path: Path) -> list[RawSample]:
        samples: list[RawSample] = []
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    samples.append(RawSample.from_row(row))
                except Exception:
                    continue
        return samples

    def _write_all_samples(self, samples: list[RawSample]) -> None:
        with self.history_file.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=RawSample.fieldnames())
            writer.writeheader()
            for sample in samples:
                writer.writerow(sample.to_row())

    def _load_samples(self) -> list[RawSample]:
        if self.history_file.exists():
            return self._read_history_file(self.history_file)
        for legacy_file in LEGACY_HISTORY_FILES:
            if not legacy_file.exists():
                continue
            samples = self._read_history_file(legacy_file)
            if samples:
                self._write_all_samples(samples)
            return samples
        return []

    def append(self, sample: RawSample) -> None:
        with self._lock:
            if self._samples and self._samples[-1].timestamp >= sample.timestamp:
                self._last_poll_monotonic = time.monotonic()
                self._last_error = None
                return
            new_file = not self.history_file.exists()
            with self.history_file.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=RawSample.fieldnames())
                if new_file:
                    writer.writeheader()
                writer.writerow(sample.to_row())
            self._samples.append(sample)
            self._last_poll_monotonic = time.monotonic()
            self._last_error = None

    def mark_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

    def snapshot(self) -> tuple[list[RawSample], float, str | None]:
        with self._lock:
            return list(self._samples), self._last_poll_monotonic, self._last_error


class HardwareCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._data: dict[str, Any] | None = None

    def get(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if self._data is not None and now - self._cached_at < HARDWARE_TTL_SECONDS:
                return dict(self._data)

        data = fetch_remote_hardware()
        with self._lock:
            self._data = data
            self._cached_at = time.monotonic()
            return dict(self._data)


class StorageCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._data: dict[str, Any] | None = None

    def get(self) -> dict[str, Any]:
        with self._lock:
            if self._data is not None:
                return dict(self._data)
        return {"timestamp": datetime.now().astimezone().isoformat(), "directories": [], "namespaces": []}

    def refresh(self) -> None:
        try:
            data = fetch_remote_storage()
        except Exception:
            return
        with self._lock:
            self._data = data
            self._cached_at = time.monotonic()

    def is_stale(self) -> bool:
        with self._lock:
            return self._data is None or (time.monotonic() - self._cached_at) >= STORAGE_TTL_SECONDS


class PayloadCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._sample_count = 0
        self._sample_timestamp = ""
        self._payload: dict[str, Any] | None = None

    def get(
        self,
        store: HistoryStore,
        hardware_cache: HardwareCache,
        storage_cache: StorageCache,
    ) -> dict[str, Any]:
        raw_samples, last_poll_monotonic, last_error = store.snapshot()
        sample_count = len(raw_samples)
        sample_timestamp = raw_samples[-1].timestamp if raw_samples else ""
        now = time.monotonic()
        with self._lock:
            if (
                self._payload is not None
                and self._sample_count == sample_count
                and self._sample_timestamp == sample_timestamp
                and now - self._cached_at < PAYLOAD_CACHE_TTL_SECONDS
            ):
                return self._payload
            payload = build_payload_from_snapshot(raw_samples, last_poll_monotonic, last_error, hardware_cache, storage_cache)
            self._payload = payload
            self._sample_count = sample_count
            self._sample_timestamp = sample_timestamp
            self._cached_at = time.monotonic()
            return payload


def ssh_python(script: str) -> str:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            REMOTE_HOST,
            "python3",
            "-",
        ],
        input=script,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def fetch_remote_sample() -> RawSample:
    payload = json.loads(ssh_python(REMOTE_DYNAMIC_SCRIPT))
    return RawSample(
        timestamp=payload["timestamp"],
        cpu_total_jiffies=int(payload["cpu_total_jiffies"]),
        cpu_idle_jiffies=int(payload["cpu_idle_jiffies"]),
        cpu_count=int(payload["cpu_count"]),
        core_stats_json=json.dumps(payload.get("core_stats", {}), sort_keys=True),
        thermal_sensors_json=json.dumps(payload.get("thermal_sensors", []), sort_keys=True),
        top_processes_json=json.dumps(payload.get("top_processes", []), sort_keys=True),
        disk_stats_json=json.dumps(payload.get("disk_stats", {}), sort_keys=True),
        active_runners_json=json.dumps(payload.get("active_runners", []), sort_keys=True),
        worker_state_json=json.dumps(payload.get("worker_state", {}), sort_keys=True),
        queue_state_json=json.dumps(payload.get("queue_state", {}), sort_keys=True),
        temp_c=float(payload["temp_c"]) if payload.get("temp_c") is not None else None,
        load1=float(payload["load1"]),
        load5=float(payload["load5"]),
        load15=float(payload["load15"]),
        mem_total_kb=int(payload["mem_total_kb"]),
        mem_available_kb=int(payload["mem_available_kb"]),
        swap_total_kb=int(payload["swap_total_kb"]),
        swap_free_kb=int(payload["swap_free_kb"]),
        disk_total_bytes=int(payload["disk_total_bytes"]),
        disk_used_bytes=int(payload["disk_used_bytes"]),
        disk_avail_bytes=int(payload["disk_avail_bytes"]),
        disk_used_pct=float(payload["disk_used_pct"]),
        rx_bytes_total=int(payload["rx_bytes_total"]),
        tx_bytes_total=int(payload["tx_bytes_total"]),
        uptime_secs=float(payload["uptime_secs"]),
        users=int(payload["users"]),
        running_processes=int(payload["running_processes"]),
        total_processes=int(payload["total_processes"]),
    )


def fetch_remote_hardware() -> dict[str, Any]:
    return json.loads(ssh_python(REMOTE_HARDWARE_SCRIPT))


def fetch_remote_storage() -> dict[str, Any]:
    return json.loads(ssh_python(REMOTE_STORAGE_SCRIPT))


def gib_from_kb(value: int) -> float:
    return value / 1024.0 / 1024.0


def gib_from_bytes(value: int) -> float:
    return value / 1024.0 / 1024.0 / 1024.0


def safe_pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator * 100.0


def load_json_value(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return default


def sort_core_names(core_names: list[str]) -> list[str]:
    return sorted(core_names, key=lambda item: int(item[3:]) if item.startswith("cpu") else item)


def round_up(value: float, step: float) -> float:
    if value <= 0:
        return step
    return (int((value + step - 1e-9) / step)) * step


def queue_reason_group(reason: str) -> str:
    base = (reason or "unknown").split(":", 1)[0].strip()
    return base or "unknown"


def build_primary_queue_state(queue_state: dict[str, Any]) -> dict[str, Any]:
    domains = queue_state.get("domains", {}) if isinstance(queue_state, dict) else {}
    discovered = queue_state.get("lock_domains", []) if isinstance(queue_state, dict) else []
    primary = domains.get(PRIMARY_QUEUE_LOCK_NAME, {}) if isinstance(domains, dict) else {}
    holders = list(primary.get("holders", []) or [])
    waiters = list(primary.get("waiters", []) or [])
    holders.sort(key=lambda item: (-int(item.get("age_seconds", 0) or 0), item.get("ticket", "")))
    waiters.sort(key=lambda item: (int(item.get("position", 0) or 0), item.get("ticket", "")))

    reason_counts: dict[str, int] = {}
    for waiter in waiters:
        label = queue_reason_group(str(waiter.get("reason", "unknown")))
        reason_counts[label] = reason_counts.get(label, 0) + 1

    wait_reason_mix = [
        {"label": label, "count": count}
        for label, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "lock_name": PRIMARY_QUEUE_LOCK_NAME,
        "capacity": PRIMARY_QUEUE_CAPACITY,
        "active_holders": int(primary.get("active_holders", len(holders)) or 0),
        "queue_depth": int(primary.get("queue_depth", len(waiters)) or 0),
        "holders": holders,
        "waiters": waiters,
        "holder_count": len(holders),
        "waiter_count": len(waiters),
        "oldest_waiter_seconds": max((int(item.get("age_seconds", 0) or 0) for item in waiters), default=0),
        "oldest_holder_seconds": max((int(item.get("age_seconds", 0) or 0) for item in holders), default=0),
        "stale_waiter_count": sum(1 for item in waiters if int(item.get("heartbeat_age_seconds", 0) or 0) >= PRIMARY_QUEUE_WAIT_STALE_SECONDS),
        "stale_holder_count": sum(1 for item in holders if int(item.get("age_seconds", 0) or 0) >= PRIMARY_QUEUE_HOLDER_STALE_SECONDS),
        "wait_reason_mix": wait_reason_mix,
        "discovered_lock_domains": sorted(discovered or list(domains.keys())),
        "other_lock_domains": [name for name in sorted(discovered or list(domains.keys())) if name != PRIMARY_QUEUE_LOCK_NAME],
    }



def build_worker_state(worker_state: dict[str, Any]) -> dict[str, Any]:
    workers_raw = list((worker_state or {}).get("workers", []) or [])
    workers: list[dict[str, Any]] = []
    active_lanes: list[dict[str, Any]] = []
    for worker in workers_raw:
        lanes = []
        for lane in list(worker.get("lanes", []) or []):
            lane_payload = {
                "worker": str(lane.get("worker") or worker.get("name") or "default"),
                "lane": str(lane.get("lane") or "lane-01"),
                "label": str(lane.get("label") or f"{worker.get('name') or 'default'}/{lane.get('lane') or 'lane-01'}"),
                "active": bool(lane.get("active")),
                "status": str(lane.get("status") or ("running" if lane.get("active") else "idle")),
                "run_tag": str(lane.get("run_tag") or ""),
                "owner": str(lane.get("owner") or ""),
                "launcher": str(lane.get("launcher") or ""),
                "container_name": str(lane.get("container_name") or ""),
                "display": str(lane.get("display") or ""),
                "artifacts_dir": str(lane.get("artifacts_dir") or ""),
                "started_at": str(lane.get("started_at") or ""),
                "heartbeat_at": str(lane.get("heartbeat_at") or ""),
                "age_seconds": int(lane.get("age_seconds", 0) or 0),
                "heartbeat_age_seconds": int(lane.get("heartbeat_age_seconds", 0) or 0),
            }
            lanes.append(lane_payload)
            if lane_payload["active"]:
                active_lanes.append(lane_payload)
        lanes.sort(key=lambda item: item["lane"])
        lane_count = int(worker.get("lane_count", len(lanes)) or len(lanes))
        active_count = int(worker.get("active_lanes", sum(1 for lane in lanes if lane["active"])) or 0)
        workers.append({
            "name": str(worker.get("name") or "default"),
            "lane_count": lane_count,
            "active_lanes": active_count,
            "idle_lanes": max(0, lane_count - active_count),
            "lanes": lanes,
        })
    workers.sort(key=lambda item: (-item["active_lanes"], item["name"]))
    active_lanes.sort(key=lambda item: (item["worker"], item["lane"]))
    total_lanes = sum(item["lane_count"] for item in workers)
    active_lane_count = len(active_lanes)
    return {
        "worker_count": len(workers),
        "busy_worker_count": sum(1 for item in workers if item["active_lanes"] > 0),
        "total_lanes": total_lanes,
        "active_lanes": active_lane_count,
        "idle_lanes": max(0, total_lanes - active_lane_count),
        "saturation_pct": round(safe_pct(active_lane_count, total_lanes), 1) if total_lanes else 0.0,
        "workers": workers,
        "active_lane_rows": active_lanes,
        "worker_names": [item["name"] for item in workers],
    }


def enrich_samples(samples: list[RawSample]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    previous: RawSample | None = None
    previous_dt: datetime | None = None
    previous_cores: dict[str, dict[str, int]] | None = None
    previous_disk: dict[str, Any] | None = None

    for sample in samples:
        current_dt = datetime.fromisoformat(sample.timestamp)
        current_cores = load_json_value(sample.core_stats_json, {})
        thermal_sensors = load_json_value(sample.thermal_sensors_json, [])
        current_disk = load_json_value(sample.disk_stats_json, {})
        active_runners = load_json_value(sample.active_runners_json, [])
        worker_state = build_worker_state(load_json_value(sample.worker_state_json, {}))
        queue = build_primary_queue_state(load_json_value(sample.queue_state_json, {}))

        mem_total_gb = gib_from_kb(sample.mem_total_kb)
        mem_available_gb = gib_from_kb(sample.mem_available_kb)
        mem_used_gb = max(mem_total_gb - mem_available_gb, 0.0)
        mem_used_pct = safe_pct(mem_used_gb, mem_total_gb)

        swap_total_gb = gib_from_kb(sample.swap_total_kb)
        swap_free_gb = gib_from_kb(sample.swap_free_kb)
        swap_used_gb = max(swap_total_gb - swap_free_gb, 0.0)
        swap_used_pct = safe_pct(swap_used_gb, swap_total_gb)

        disk_total_gb = gib_from_bytes(sample.disk_total_bytes)
        disk_used_gb = gib_from_bytes(sample.disk_used_bytes)
        disk_avail_gb = gib_from_bytes(sample.disk_avail_bytes)

        cpu_usage_pct: float | None = None
        rx_mib_s: float | None = None
        tx_mib_s: float | None = None
        disk_read_mib_s: float | None = None
        disk_write_mib_s: float | None = None
        disk_busy_pct: float | None = None
        disk_iops: float | None = None
        disk_await_ms: float | None = None
        per_core_pct: dict[str, float | None] = {name: None for name in sort_core_names(list(current_cores.keys()))}

        if previous is not None and previous_dt is not None:
            delta_seconds = (current_dt - previous_dt).total_seconds()
            if delta_seconds > 0:
                total_delta = sample.cpu_total_jiffies - previous.cpu_total_jiffies
                idle_delta = sample.cpu_idle_jiffies - previous.cpu_idle_jiffies
                if total_delta > 0:
                    cpu_usage_pct = max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100.0))
                rx_delta = sample.rx_bytes_total - previous.rx_bytes_total
                tx_delta = sample.tx_bytes_total - previous.tx_bytes_total
                if rx_delta >= 0:
                    rx_mib_s = rx_delta / delta_seconds / 1024.0 / 1024.0
                if tx_delta >= 0:
                    tx_mib_s = tx_delta / delta_seconds / 1024.0 / 1024.0
                if previous_cores is not None:
                    for core_name in per_core_pct:
                        prev = previous_cores.get(core_name)
                        current = current_cores.get(core_name)
                        if not prev or not current:
                            continue
                        core_total_delta = int(current["total"]) - int(prev["total"])
                        core_idle_delta = int(current["idle"]) - int(prev["idle"])
                        if core_total_delta > 0:
                            per_core_pct[core_name] = round(
                                max(0.0, min(100.0, (core_total_delta - core_idle_delta) / core_total_delta * 100.0)),
                                1,
                            )
                if previous_disk and current_disk and previous_disk.get("device") == current_disk.get("device"):
                    read_sector_delta = int(current_disk.get("read_sectors", 0)) - int(previous_disk.get("read_sectors", 0))
                    write_sector_delta = int(current_disk.get("write_sectors", 0)) - int(previous_disk.get("write_sectors", 0))
                    io_time_delta = int(current_disk.get("io_ms", 0)) - int(previous_disk.get("io_ms", 0))
                    read_ios_delta = int(current_disk.get("read_ios", 0)) - int(previous_disk.get("read_ios", 0))
                    write_ios_delta = int(current_disk.get("write_ios", 0)) - int(previous_disk.get("write_ios", 0))
                    read_ms_delta = int(current_disk.get("read_ms", 0)) - int(previous_disk.get("read_ms", 0))
                    write_ms_delta = int(current_disk.get("write_ms", 0)) - int(previous_disk.get("write_ms", 0))
                    if read_sector_delta >= 0:
                        disk_read_mib_s = read_sector_delta * 512.0 / delta_seconds / 1024.0 / 1024.0
                    if write_sector_delta >= 0:
                        disk_write_mib_s = write_sector_delta * 512.0 / delta_seconds / 1024.0 / 1024.0
                    if io_time_delta >= 0:
                        disk_busy_pct = max(0.0, min(100.0, io_time_delta / (delta_seconds * 10.0)))
                    ops_delta = read_ios_delta + write_ios_delta
                    if read_ios_delta >= 0 and write_ios_delta >= 0:
                        disk_iops = ops_delta / delta_seconds
                    if ops_delta > 0 and read_ms_delta >= 0 and write_ms_delta >= 0:
                        disk_await_ms = (read_ms_delta + write_ms_delta) / ops_delta

        queue_oldest_waiter_minutes = round(queue["oldest_waiter_seconds"] / 60.0, 1)
        queue_oldest_holder_minutes = round(queue["oldest_holder_seconds"] / 60.0, 1)
        queue_saturation_pct = safe_pct(queue["active_holders"], queue["capacity"]) if queue["capacity"] else 0.0
        active_runner_count = len(active_runners)
        active_worker_lanes = worker_state["active_lanes"]
        total_worker_lanes = worker_state["total_lanes"]
        coordination_gap = active_runner_count > 0 and active_worker_lanes == 0

        enriched.append(
            {
                "timestamp": sample.timestamp,
                "cpu_pct": round(cpu_usage_pct, 1) if cpu_usage_pct is not None else None,
                "per_core_pct": per_core_pct,
                "load1": round(sample.load1, 2),
                "load5": round(sample.load5, 2),
                "load15": round(sample.load15, 2),
                "load1_pct": round(sample.load1 / max(sample.cpu_count, 1) * 100.0, 1),
                "load5_pct": round(sample.load5 / max(sample.cpu_count, 1) * 100.0, 1),
                "load15_pct": round(sample.load15 / max(sample.cpu_count, 1) * 100.0, 1),
                "temp_c": sample.temp_c,
                "thermal_sensors": thermal_sensors,
                "mem_used_pct": round(mem_used_pct, 1),
                "mem_used_gb": round(mem_used_gb, 1),
                "mem_total_gb": round(mem_total_gb, 1),
                "mem_available_gb": round(mem_available_gb, 1),
                "swap_used_pct": round(swap_used_pct, 1),
                "swap_used_gb": round(swap_used_gb, 1),
                "swap_total_gb": round(swap_total_gb, 1),
                "disk_used_pct": round(sample.disk_used_pct, 1),
                "disk_used_gb": round(disk_used_gb, 1),
                "disk_total_gb": round(disk_total_gb, 1),
                "disk_avail_gb": round(disk_avail_gb, 1),
                "disk_device": current_disk.get("device", ""),
                "disk_read_mib_s": round(disk_read_mib_s, 3) if disk_read_mib_s is not None else None,
                "disk_write_mib_s": round(disk_write_mib_s, 3) if disk_write_mib_s is not None else None,
                "disk_busy_pct": round(disk_busy_pct, 1) if disk_busy_pct is not None else None,
                "disk_iops": round(disk_iops, 1) if disk_iops is not None else None,
                "disk_await_ms": round(disk_await_ms, 1) if disk_await_ms is not None else None,
                "rx_mib_s": round(rx_mib_s, 3) if rx_mib_s is not None else None,
                "tx_mib_s": round(tx_mib_s, 3) if tx_mib_s is not None else None,
                "uptime_hours": round(sample.uptime_secs / 3600.0, 1),
                "users": sample.users,
                "running_processes": sample.running_processes,
                "total_processes": sample.total_processes,
                "cpu_count": sample.cpu_count,
                "active_runners": active_runners,
                "active_runner_labels": [runner.get("label", "?") for runner in active_runners if runner.get("label")],
                "active_runner_count": active_runner_count,
                "worker_names": worker_state["worker_names"],
                "worker_count": worker_state["worker_count"],
                "busy_worker_count": worker_state["busy_worker_count"],
                "active_worker_lanes": active_worker_lanes,
                "total_worker_lanes": total_worker_lanes,
                "idle_worker_lanes": worker_state["idle_lanes"],
                "worker_saturation_pct": worker_state["saturation_pct"],
                "queue_depth": queue["queue_depth"],
                "queue_active_holders": queue["active_holders"],
                "queue_capacity": queue["capacity"],
                "queue_saturation_pct": round(queue_saturation_pct, 1),
                "queue_oldest_waiter_minutes": queue_oldest_waiter_minutes,
                "queue_oldest_holder_minutes": queue_oldest_holder_minutes,
                "queue_waiter_count": queue["waiter_count"],
                "queue_holder_count": queue["holder_count"],
                "queue_stale_waiter_count": queue["stale_waiter_count"],
                "queue_stale_holder_count": queue["stale_holder_count"],
                "coordination_gap": coordination_gap,
            }
        )
        previous = sample
        previous_dt = current_dt
        previous_cores = current_cores
        previous_disk = current_disk

    latest_total_worker_lanes = next((item["total_worker_lanes"] for item in reversed(enriched) if item.get("total_worker_lanes", 0) > 0), 0)
    latest_worker_names = next((item["worker_names"] for item in reversed(enriched) if item.get("worker_names")), [])
    for item in enriched:
        if item.get("total_worker_lanes", 0) == 0 and item.get("active_runner_count", 0) > 0:
            item["active_worker_lanes"] = max(item.get("active_worker_lanes", 0), item.get("active_runner_count", 0))
            item["total_worker_lanes"] = max(item.get("total_worker_lanes", 0), latest_total_worker_lanes or item["active_worker_lanes"])
            item["busy_worker_count"] = max(item.get("busy_worker_count", 0), 1)
            item["worker_count"] = max(item.get("worker_count", 0), 1)
            item["idle_worker_lanes"] = max(0, item["total_worker_lanes"] - item["active_worker_lanes"])
            item["worker_saturation_pct"] = round(safe_pct(item["active_worker_lanes"], item["total_worker_lanes"]), 1) if item["total_worker_lanes"] else 0.0
            if not item.get("worker_names"):
                item["worker_names"] = latest_worker_names or ["legacy"]

    return enriched


def build_process_trends(raw_samples: list[RawSample], window_minutes: int = 720) -> dict[str, Any]:
    if not raw_samples:
        return {"window_minutes": window_minutes, "metric": "swap_mib", "lines": []}

    latest_dt = datetime.fromisoformat(raw_samples[-1].timestamp)
    cutoff = latest_dt - timedelta(minutes=window_minutes)
    window = [sample for sample in raw_samples if datetime.fromisoformat(sample.timestamp) >= cutoff]
    if not window:
        window = raw_samples[-180:]

    rows_by_sample: list[tuple[str, list[dict[str, Any]]]] = []
    score_by_name: dict[str, float] = {}
    max_swap = 0.0
    max_rss = 0.0
    for sample in window:
        rows = json.loads(sample.top_processes_json)
        rows_by_sample.append((sample.timestamp, rows))
        for row in rows:
            name = row.get("name", "?")
            swap_mib = float(row.get("swap_mib", 0.0))
            rss_mib = float(row.get("rss_mib", 0.0))
            score_by_name[name] = max(score_by_name.get(name, 0.0), swap_mib * 2.0 + rss_mib)
            max_swap = max(max_swap, swap_mib)
            max_rss = max(max_rss, rss_mib)

    if not score_by_name:
        return {"window_minutes": window_minutes, "metric": "swap_mib", "lines": []}

    metric = "swap_mib" if max_swap >= 64.0 else "rss_mib"
    names = [name for name, _ in sorted(score_by_name.items(), key=lambda item: item[1], reverse=True)[:4]]
    lines: list[dict[str, Any]] = []
    for name in names:
        points = []
        latest_value = None
        peak_value = 0.0
        for timestamp, rows in rows_by_sample:
            matches = [row for row in rows if row.get("name") == name]
            if matches:
                best = max(matches, key=lambda row: (float(row.get(metric, 0.0)), float(row.get("rss_mib", 0.0))))
                value = float(best.get(metric, 0.0))
                latest_value = value
                peak_value = max(peak_value, value)
            else:
                value = None
            points.append({"x": timestamp, "y": value})
        lines.append(
            {
                "name": name,
                "points": points,
                "latest_value": round(latest_value or 0.0, 1),
                "peak_value": round(peak_value, 1),
            }
        )

    return {
        "window_minutes": window_minutes,
        "metric": metric,
        "lines": lines,
    }


def build_disk_events(series: list[dict[str, Any]], threshold_gb: float = 2.0) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    run: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal run
        if run and abs(run["delta_gb"]) >= threshold_gb:
            events.append(
                {
                    "timestamp": run["timestamp"],
                    "delta_gb": round(run["delta_gb"], 1),
                    "kind": run["kind"],
                    "label": ("Freed" if run["kind"] == "cleanup" else "Growth") + f" {abs(run['delta_gb']):.1f} GiB",
                }
            )
        run = None

    for previous, current in zip(series, series[1:]):
        delta = current["disk_used_gb"] - previous["disk_used_gb"]
        current_dt = datetime.fromisoformat(current["timestamp"])
        if delta <= -0.5:
            kind = "cleanup"
        elif delta >= 0.5:
            kind = "growth"
        else:
            flush()
            continue
        if run and run["kind"] == kind and current_dt - run["last_dt"] <= timedelta(minutes=20):
            run["delta_gb"] += delta
            run["timestamp"] = current["timestamp"]
            run["last_dt"] = current_dt
        else:
            flush()
            run = {
                "kind": kind,
                "delta_gb": delta,
                "timestamp": current["timestamp"],
                "last_dt": current_dt,
            }
    flush()
    return events[-6:]


def build_runner_activity(raw_samples: list[RawSample], limit: int = 12) -> dict[str, Any]:
    if not raw_samples:
        return {"active": [], "recent": []}

    recent: list[dict[str, Any]] = []
    previous_map: dict[str, dict[str, Any]] | None = None
    for sample in raw_samples:
        current_rows = load_json_value(sample.active_runners_json, [])
        current_map = {row.get("label"): row for row in current_rows if row.get("label")}
        if previous_map is None:
            previous_map = current_map
            continue
        started = sorted(set(current_map) - set(previous_map))
        stopped = sorted(set(previous_map) - set(current_map))
        for label in started:
            row = current_map[label]
            recent.append(
                {
                    "timestamp": sample.timestamp,
                    "kind": "start",
                    "label": label,
                    "driver": row.get("driver", ""),
                    "root": row.get("root", ""),
                    "path": row.get("path", ""),
                }
            )
        for label in stopped:
            row = previous_map[label]
            recent.append(
                {
                    "timestamp": sample.timestamp,
                    "kind": "stop",
                    "label": label,
                    "driver": row.get("driver", ""),
                    "root": row.get("root", ""),
                    "path": row.get("path", ""),
                }
            )
        previous_map = current_map

    latest_timestamp = datetime.fromisoformat(raw_samples[-1].timestamp)
    latest_rows = load_json_value(raw_samples[-1].active_runners_json, [])
    active: list[dict[str, Any]] = []
    for row in latest_rows:
        label = row.get("label")
        if not label:
            continue
        first_seen = raw_samples[-1].timestamp
        for sample in reversed(raw_samples[:-1]):
            labels = {
                runner.get("label")
                for runner in load_json_value(sample.active_runners_json, [])
                if runner.get("label")
            }
            if label in labels:
                first_seen = sample.timestamp
            else:
                break
        seen_minutes = max(0.0, (latest_timestamp - datetime.fromisoformat(first_seen)).total_seconds() / 60.0)
        active.append(
            {
                "label": label,
                "root": row.get("root", ""),
                "kind": row.get("kind", ""),
                "name": row.get("name", ""),
                "path": row.get("path", ""),
                "driver": row.get("driver", ""),
                "pid_count": int(row.get("pid_count", 0) or 0),
                "since": first_seen,
                "seen_minutes": round(seen_minutes, 1),
            }
        )

    active.sort(key=lambda item: (-item["seen_minutes"], item["label"]))
    return {
        "active": active,
        "recent": recent[-limit:],
    }


def build_worker_activity(raw_samples: list[RawSample], limit: int = 96) -> dict[str, Any]:
    if not raw_samples:
        return {"active": [], "recent": [], "lanes": []}

    recent: list[dict[str, Any]] = []
    previous_map: dict[str, dict[str, Any]] | None = None
    for sample in raw_samples:
        state = build_worker_state(load_json_value(sample.worker_state_json, {}))
        current_rows = {row["label"]: row for row in state["active_lane_rows"] if row.get("label")}
        if previous_map is None:
            previous_map = current_rows
            continue
        started = sorted(set(current_rows) - set(previous_map))
        stopped = sorted(set(previous_map) - set(current_rows))
        for label in started:
            row = current_rows[label]
            recent.append(
                {
                    "timestamp": sample.timestamp,
                    "kind": "start",
                    "label": label,
                    "driver": row.get("launcher", ""),
                    "worker": row.get("worker", ""),
                    "lane": row.get("lane", ""),
                    "path": " · ".join(part for part in [row.get("owner", ""), row.get("launcher", ""), row.get("run_tag", "")] if part),
                    "run_tag": row.get("run_tag", ""),
                }
            )
        for label in stopped:
            row = previous_map[label]
            recent.append(
                {
                    "timestamp": sample.timestamp,
                    "kind": "stop",
                    "label": label,
                    "driver": row.get("launcher", ""),
                    "worker": row.get("worker", ""),
                    "lane": row.get("lane", ""),
                    "path": " · ".join(part for part in [row.get("owner", ""), row.get("launcher", ""), row.get("run_tag", "")] if part),
                    "run_tag": row.get("run_tag", ""),
                }
            )
        previous_map = current_rows

    latest_timestamp = datetime.fromisoformat(raw_samples[-1].timestamp)
    latest_state = build_worker_state(load_json_value(raw_samples[-1].worker_state_json, {}))
    active: list[dict[str, Any]] = []
    active_by_label = {row.get("label"): row for row in latest_state["active_lane_rows"] if row.get("label")}
    for row in latest_state["active_lane_rows"]:
        label = row.get("label")
        if not label:
            continue
        first_seen = raw_samples[-1].timestamp
        for sample in reversed(raw_samples[:-1]):
            state = build_worker_state(load_json_value(sample.worker_state_json, {}))
            labels = {lane.get("label") for lane in state["active_lane_rows"] if lane.get("label")}
            if label in labels:
                first_seen = sample.timestamp
            else:
                break
        seen_minutes = max(0.0, (latest_timestamp - datetime.fromisoformat(first_seen)).total_seconds() / 60.0)
        descriptor = " · ".join(part for part in [row.get("owner", ""), row.get("launcher", ""), row.get("run_tag", ""), row.get("display", "")] if part)
        active.append(
            {
                "label": label,
                "root": row.get("worker", ""),
                "kind": "worker-lane",
                "name": row.get("lane", ""),
                "path": descriptor or row.get("artifacts_dir", ""),
                "driver": row.get("launcher", ""),
                "pid_count": 1,
                "since": first_seen,
                "seen_minutes": round(seen_minutes, 1),
                "worker": row.get("worker", ""),
                "lane": row.get("lane", ""),
                "run_tag": row.get("run_tag", ""),
                "owner": row.get("owner", ""),
                "display": row.get("display", ""),
                "container_name": row.get("container_name", ""),
            }
        )
    all_lane_defs: list[dict[str, Any]] = []
    for worker in latest_state["workers"]:
        for lane in worker.get("lanes", []):
            if lane.get("label"):
                all_lane_defs.append(lane)
    all_lane_defs.sort(key=lambda item: (item.get("worker", ""), item.get("lane", "")))

    # Pair recent start/stop events per lane so the dashboard can render one block per lane.
    events_by_lane: dict[str, list[dict[str, Any]]] = {}
    for event in recent:
        events_by_lane.setdefault(event.get("label", ""), []).append(event)

    lane_rows: list[dict[str, Any]] = []
    for lane_def in all_lane_defs:
        label = lane_def.get("label", "")
        lane_events = sorted(events_by_lane.get(label, []), key=lambda item: item["timestamp"])
        last_completed: dict[str, Any] | None = None
        pending_start: dict[str, Any] | None = None
        for event in lane_events:
            if event["kind"] == "start":
                pending_start = event
            elif event["kind"] == "stop" and pending_start:
                last_completed = {"start": pending_start, "stop": event}
                pending_start = None
        active_row = active_by_label.get(label)
        if active_row:
            descriptor = " · ".join(part for part in [active_row.get("owner", ""), active_row.get("launcher", ""), active_row.get("run_tag", ""), active_row.get("display", "")] if part)
            lane_rows.append(
                {
                    "label": label,
                    "worker": active_row.get("worker", lane_def.get("worker", "")),
                    "lane": active_row.get("lane", lane_def.get("lane", "")),
                    "status": "live",
                    "live": True,
                    "since": active_row.get("since", raw_samples[-1].timestamp),
                    "seen_minutes": active_row.get("seen_minutes", 0.0),
                    "path": descriptor or active_row.get("artifacts_dir", ""),
                    "driver": active_row.get("driver", ""),
                    "run_tag": active_row.get("run_tag", ""),
                    "owner": active_row.get("owner", ""),
                    "display": active_row.get("display", ""),
                    "container_name": active_row.get("container_name", ""),
                }
            )
        elif last_completed:
            start = last_completed["start"]
            stop = last_completed["stop"]
            lane_rows.append(
                {
                    "label": label,
                    "worker": lane_def.get("worker", ""),
                    "lane": lane_def.get("lane", ""),
                    "status": "completed",
                    "live": False,
                    "started_at": start["timestamp"],
                    "ended_at": stop["timestamp"],
                    "path": start.get("path") or stop.get("path") or label,
                    "driver": start.get("driver") or stop.get("driver") or "driver n/a",
                    "run_tag": start.get("run_tag") or stop.get("run_tag") or "",
                    "owner": start.get("worker", "") or stop.get("worker", ""),
                    "display": "",
                    "container_name": "",
                }
            )
        else:
            lane_rows.append(
                {
                    "label": label,
                    "worker": lane_def.get("worker", ""),
                    "lane": lane_def.get("lane", ""),
                    "status": "idle",
                    "live": False,
                    "path": "",
                    "driver": "",
                    "run_tag": "",
                    "owner": "",
                    "display": "",
                    "container_name": "",
                }
            )

    active.sort(key=lambda item: (item.get("worker", ""), item.get("lane", "")))
    lane_rows.sort(key=lambda item: (item.get("worker", ""), item.get("lane", "")))
    return {
        "active": active,
        "recent": recent[-limit:],
        "lanes": lane_rows,
    }


def build_queue_activity(raw_samples: list[RawSample], limit: int = 16) -> dict[str, Any]:
    if not raw_samples:
        return {"recent": []}

    recent: list[dict[str, Any]] = []
    previous_waiters: dict[str, dict[str, Any]] | None = None
    previous_holders: dict[str, dict[str, Any]] | None = None

    def event(kind: str, timestamp: str, row: dict[str, Any], note: str = "") -> dict[str, Any]:
        return {
            "timestamp": timestamp,
            "kind": kind,
            "label": row.get("owner") or row.get("ticket") or kind,
            "ticket": row.get("ticket", ""),
            "reason": row.get("reason", "unknown"),
            "host": row.get("host", ""),
            "pid": int(row.get("pid", 0) or 0),
            "position": int(row.get("position", 0) or 0),
            "note": note,
        }

    for sample in raw_samples:
        queue = build_primary_queue_state(load_json_value(sample.queue_state_json, {}))
        current_waiters = {row.get("ticket"): row for row in queue["waiters"] if row.get("ticket")}
        current_holders = {row.get("ticket"): row for row in queue["holders"] if row.get("ticket")}

        if previous_waiters is not None and previous_holders is not None:
            for ticket, row in current_waiters.items():
                if ticket not in previous_waiters and ticket not in previous_holders:
                    recent.append(event("queued", sample.timestamp, row, f"position {int(row.get('position', 0) or 0)}"))
            for ticket, row in current_holders.items():
                if ticket not in previous_holders:
                    previous_wait = previous_waiters.get(ticket) if previous_waiters else None
                    note = f"from position {int(previous_wait.get('position', 0) or 0)}" if previous_wait else "immediate slot"
                    recent.append(event("acquired", sample.timestamp, row, note))
            for ticket, row in previous_holders.items():
                if ticket not in current_holders and ticket not in current_waiters:
                    recent.append(event("released", sample.timestamp, row))
            for ticket, row in previous_waiters.items():
                if ticket not in current_waiters and ticket not in current_holders:
                    recent.append(event("dequeued", sample.timestamp, row))

        previous_waiters = current_waiters
        previous_holders = current_holders

    return {
        "lock_name": PRIMARY_QUEUE_LOCK_NAME,
        "capacity": PRIMARY_QUEUE_CAPACITY,
        "recent": recent[-limit:],
    }


def build_queue_alerts(stale: bool, last_error: str | None, latest: dict[str, Any], queue: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    if stale:
        alerts.append({"level": "critical", "title": "Collector stale", "text": "Dashboard polling is behind the expected cadence."})
    elif last_error:
        alerts.append({"level": "warn", "title": "Collector error", "text": last_error})
    if queue["capacity"] > 0 and queue["active_holders"] >= queue["capacity"]:
        alerts.append({"level": "warn", "title": "Queue saturated", "text": f"{queue['active_holders']} of {queue['capacity']} holder slots are occupied."})
    if queue["queue_depth"] > 0 and queue["oldest_waiter_seconds"] >= PRIMARY_QUEUE_SLOT_SECONDS:
        alerts.append({"level": "warn", "title": "Long queue wait", "text": f"Oldest waiter has been queued for {queue['oldest_waiter_seconds'] // 60} minutes."})
    if queue["stale_waiter_count"] > 0:
        alerts.append({"level": "critical", "title": "Stale waiters", "text": f"{queue['stale_waiter_count']} waiter entries look stale and may need cleanup."})
    if queue["stale_holder_count"] > 0:
        alerts.append({"level": "critical", "title": "Stale holders", "text": f"{queue['stale_holder_count']} holder entries exceed the stale heartbeat threshold."})
    if latest.get("coordination_gap"):
        alerts.append({"level": "critical", "title": "Coordination gap", "text": "Runner processes are active without a matching runner-host lock holder."})
    return alerts


def classify_status(latest: dict[str, Any]) -> str:
    if (
        latest.get("coordination_gap")
        or latest.get("queue_stale_waiter_count", 0) > 0
        or latest.get("queue_stale_holder_count", 0) > 0
        or latest.get("queue_oldest_waiter_minutes", 0.0) >= 20.0
        or (latest.get("temp_c") or 0.0) >= 85.0
        or latest["swap_used_pct"] >= 90.0
        or latest["load1"] > latest["cpu_count"] * 1.4
        or latest["disk_used_pct"] >= 90.0
        or (latest.get("disk_busy_pct") or 0.0) >= 85.0
    ):
        return "attention"
    if (
        latest.get("queue_depth", 0) > 0
        or latest.get("queue_active_holders", 0) >= latest.get("queue_capacity", 0) > 0
        or (latest.get("temp_c") or 0.0) >= 75.0
        or latest["swap_used_pct"] >= 75.0
        or latest["load1"] > latest["cpu_count"]
        or latest["disk_used_pct"] >= 82.0
        or (latest.get("disk_busy_pct") or 0.0) >= 65.0
    ):
        return "busy"
    return "steady"


def build_notes(latest: dict[str, Any], top_processes: list[dict[str, Any]], per_core_temp_available: bool, queue: dict[str, Any], worker_state: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if not per_core_temp_available:
        notes.append("Per-core thermal sensors are not exposed on this host; the dashboard shows package and board thermal zones instead.")
    if latest["load1"] > latest["cpu_count"]:
        notes.append("Load average is above core count.")
    if latest["swap_used_pct"] >= 85.0:
        notes.append("Swap is heavily used. The biggest swap owner should be treated as the first suspect.")
    if latest["disk_used_pct"] >= 85.0:
        notes.append("Root filesystem is getting tight.")
    if (latest.get("disk_busy_pct") or 0.0) >= 70.0:
        device = latest.get("disk_device") or "root disk"
        notes.append(f"{device} is busy at {latest['disk_busy_pct']:.1f}%.")
    if (latest.get("temp_c") or 0.0) >= 80.0:
        notes.append("CPU package temperature is elevated.")
    if worker_state.get("active_lanes", 0) > 0:
        notes.append(
            f"{worker_state['active_lanes']} worker lane{'s' if worker_state['active_lanes'] != 1 else ''} active across {worker_state['busy_worker_count']} worker{'s' if worker_state['busy_worker_count'] != 1 else ''}."
        )
    elif latest.get("active_runner_count", 0) > 0:
        count = latest["active_runner_count"]
        notes.append(f"{count} legacy runner context{'s' if count != 1 else ''} active outside worker leases.")
    if queue["queue_depth"] > 0:
        notes.append(f"Host admission queue depth is {queue['queue_depth']} with the oldest wait at {latest['queue_oldest_waiter_minutes']:.1f} minutes.")
    if queue["other_lock_domains"]:
        notes.append("Additional lock domains are active alongside worker leases.")
    if latest.get("coordination_gap"):
        notes.append("A coordination gap is present: legacy runner activity exists without a matching worker lease holder.")
    if top_processes:
        first = top_processes[0]
        if first.get("swap_mib", 0.0) >= 512.0:
            notes.append(f"Top pressure actor is PID {first['pid']} {first['name']} with {first['swap_mib']:.1f} MiB swapped.")
    if not notes:
        notes.append("No obvious pressure indicators at the moment.")
    return notes


def collector_loop(store: HistoryStore) -> None:
    while True:
        try:
            store.append(fetch_remote_sample())
        except Exception as exc:  # pragma: no cover
            store.mark_error(str(exc))
        time.sleep(POLL_INTERVAL_SECONDS)


def storage_loop(storage_cache: StorageCache) -> None:
    while True:
        storage_cache.refresh()
        time.sleep(STORAGE_TTL_SECONDS)


def select_payload_samples(raw_samples: list[RawSample]) -> list[RawSample]:
    if len(raw_samples) <= MAX_PAYLOAD_SERIES_SAMPLES:
        return raw_samples
    # Keep one extra predecessor so rate-based charts retain accurate first-window deltas.
    return raw_samples[-(MAX_PAYLOAD_SERIES_SAMPLES + 1):]


def build_payload_from_snapshot(
    raw_samples: list[RawSample],
    last_poll_monotonic: float,
    last_error: str | None,
    hardware_cache: HardwareCache,
    storage_cache: StorageCache,
) -> dict[str, Any]:
    if not raw_samples:
        raise RuntimeError("no samples collected yet")

    total_sample_count = len(raw_samples)
    derivation_samples = select_payload_samples(raw_samples)
    enriched = enrich_samples(derivation_samples)
    series = enriched[-MAX_PAYLOAD_SERIES_SAMPLES:]
    activity_samples = derivation_samples[-len(series):]
    latest = series[-1]
    latest_raw = raw_samples[-1]
    top_processes = json.loads(latest_raw.top_processes_json)
    queue = build_primary_queue_state(load_json_value(latest_raw.queue_state_json, {}))
    worker_state = build_worker_state(load_json_value(latest_raw.worker_state_json, {}))
    thermal_sensors = latest["thermal_sensors"]
    per_core_temp_available = any(sensor.get("kind") == "core" for sensor in thermal_sensors)
    thermal_labels = [sensor.get("label", "?") for sensor in thermal_sensors]
    core_names = sort_core_names(list(latest["per_core_pct"].keys()))
    stale = (time.monotonic() - last_poll_monotonic) > (POLL_INTERVAL_SECONDS * 2.5)
    hardware = hardware_cache.get()
    storage = storage_cache.get()
    process_trends = build_process_trends(activity_samples)
    disk_events = build_disk_events(series)
    runner_activity = build_runner_activity(activity_samples)
    worker_activity = build_worker_activity(activity_samples)
    queue_activity = build_queue_activity(activity_samples)
    alerts = build_queue_alerts(stale, last_error, latest, queue)
    retained_seconds = max(
        0.0,
        (datetime.fromisoformat(series[-1]["timestamp"]) - datetime.fromisoformat(series[0]["timestamp"])).total_seconds(),
    )

    return {
        "host": REMOTE_NAME,
        "remote_host": REMOTE_HOST,
        "sample_count": len(series),
        "retained_sample_count": len(series),
        "total_sample_count": total_sample_count,
        "max_payload_series_samples": MAX_PAYLOAD_SERIES_SAMPLES,
        "payload_cache_ttl_seconds": PAYLOAD_CACHE_TTL_SECONDS,
        "series_retention_hours": round(retained_seconds / 3600.0, 1),
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "history_started_at": series[0]["timestamp"],
        "updated_at": latest["timestamp"],
        "stale": stale,
        "last_error": last_error,
        "status": classify_status(latest),
        "latest": latest,
        "notes": build_notes(latest, top_processes, per_core_temp_available, queue, worker_state),
        "alerts": alerts,
        "series": series,
        "hardware": hardware,
        "top_processes": top_processes,
        "thermal_labels": thermal_labels,
        "per_core_temp_available": per_core_temp_available,
        "core_names": core_names,
        "storage": storage,
        "process_trends": process_trends,
        "disk_events": disk_events,
        "runner_activity": runner_activity,
        "worker_state": worker_state,
        "worker_activity": worker_activity,
        "queue": queue,
        "queue_activity": queue_activity,
    }


def build_payload(store: HistoryStore, hardware_cache: HardwareCache, storage_cache: StorageCache) -> dict[str, Any]:
    raw_samples, last_poll_monotonic, last_error = store.snapshot()
    return build_payload_from_snapshot(raw_samples, last_poll_monotonic, last_error, hardware_cache, storage_cache)


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>tiny-m73 system monitor</title>
  <style>
    :root {
      --bg: #f2ebdf;
      --ink: #1d2430;
      --muted: #5d6975;
      --panel: rgba(255, 251, 246, 0.84);
      --panel-2: rgba(255, 255, 255, 0.58);
      --line: rgba(39, 47, 58, 0.09);
      --shadow: 0 20px 56px rgba(64, 40, 14, 0.10);
      --cpu: #db7a31;
      --load: #91801d;
      --mem: #2d7f73;
      --swap: #7b5cb6;
      --disk: #a15f17;
      --temp: #cf4d37;
      --zone: #d5964a;
      --rx: #2f6cca;
      --tx: #1d996f;
      --steady: #2d7f73;
      --busy: #b67918;
      --attention: #b33b27;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      color: var(--ink);
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(215, 112, 54, 0.16), transparent 30rem),
        radial-gradient(circle at 90% 18%, rgba(39, 129, 122, 0.15), transparent 24rem),
        radial-gradient(circle at bottom right, rgba(42, 92, 181, 0.10), transparent 28rem),
        var(--bg);
    }

    .wrap {
      max-width: 1600px;
      margin: 0 auto;
      padding: 34px 22px 56px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid rgba(74, 62, 48, 0.08);
      border-radius: 26px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }

    .hero {
      display: grid;
      grid-template-columns: 1.18fr 0.82fr;
      gap: 18px;
      margin-bottom: 18px;
    }

    .hero-main,
    .hero-side {
      padding: 32px;
    }

    .eyebrow {
      font-size: 13px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 10px;
    }

    h1 {
      margin: 0;
      font-size: clamp(2.5rem, 5.2vw, 5.1rem);
      line-height: 0.9;
      font-weight: 780;
      max-width: 10ch;
    }

    .hero-copy {
      margin-top: 12px;
      color: var(--muted);
      font-size: 1.03rem;
      line-height: 1.6;
      max-width: 62ch;
    }

    .hero-meta {
      margin-top: 16px;
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.6;
    }

    .headline-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
    }

    .headline-chip {
      background: var(--panel-2);
      border: 1px solid rgba(74, 62, 48, 0.08);
      border-radius: 18px;
      padding: 14px 16px;
    }

    .chip-k {
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.09em;
      margin-bottom: 4px;
    }

    .chip-v {
      font-size: 1.2rem;
      font-weight: 740;
    }

    .temp-row {
      display: flex;
      align-items: baseline;
      gap: 14px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }

    .temp-big {
      font-size: clamp(3rem, 8vw, 6rem);
      line-height: 0.85;
      letter-spacing: -0.06em;
      font-weight: 790;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      color: white;
      text-transform: uppercase;
      letter-spacing: 0.09em;
      font-size: 0.88rem;
      font-weight: 760;
    }

    .badge.steady { background: var(--steady); }
    .badge.busy { background: var(--busy); }
    .badge.attention { background: var(--attention); }

    .diag-list {
      margin: 16px 0 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.55;
    }

    .alert-rail {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }

    .alert-rail:empty {
      display: none;
    }

    .alert-box {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(74, 62, 48, 0.08);
      background: var(--panel);
      box-shadow: var(--shadow);
    }

    .alert-box.warn {
      background: rgba(255, 247, 230, 0.94);
      border-color: rgba(182, 121, 24, 0.20);
    }

    .alert-box.critical {
      background: rgba(255, 238, 232, 0.94);
      border-color: rgba(179, 59, 39, 0.22);
    }

    .alert-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
    }

    .alert-title {
      font-size: 0.94rem;
      font-weight: 720;
    }

    .alert-level {
      font-size: 0.64rem;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      font-weight: 760;
      color: var(--muted);
    }

    .alert-text {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }

    .dashboard-tabs {
      position: sticky;
      top: 10px;
      z-index: 20;
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      padding: 12px;
      margin-bottom: 18px;
      overflow-x: auto;
    }

    .dashboard-tab-copy {
      min-width: 14rem;
      padding: 0 8px;
    }

    .dashboard-tab-title {
      font-size: 0.78rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 760;
    }

    .dashboard-tab-note {
      color: var(--muted);
      font-size: 0.88rem;
      margin-top: 2px;
      white-space: nowrap;
    }

    .tab-list {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
    }

    .tab-btn {
      border: 1px solid rgba(74, 62, 48, 0.12);
      background: rgba(255, 255, 255, 0.74);
      color: var(--muted);
      border-radius: 16px;
      padding: 10px 14px;
      font: inherit;
      font-size: 0.88rem;
      font-weight: 700;
      cursor: pointer;
      transition: background 140ms ease, color 140ms ease, border-color 140ms ease, transform 140ms ease;
    }

    .tab-btn:hover {
      transform: translateY(-1px);
      border-color: rgba(74, 62, 48, 0.24);
    }

    .tab-btn.active {
      background: var(--ink);
      color: #fff8f0;
      border-color: var(--ink);
    }

    .tabbed-panel {
      display: none;
    }

    body[data-active-page="overview"] .tabbed-panel[data-pages~="overview"],
    body[data-active-page="workers"] .tabbed-panel[data-pages~="workers"],
    body[data-active-page="host"] .tabbed-panel[data-pages~="host"],
    body[data-active-page="storage"] .tabbed-panel[data-pages~="storage"],
    body[data-active-page="diagnostics"] .tabbed-panel[data-pages~="diagnostics"] {
      display: block;
    }

    .pressure {
      padding: 22px 24px 24px;
      margin-bottom: 20px;
    }

    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }

    .section-title {
      font-size: 1.24rem;
      font-weight: 760;
    }

    .section-note {
      color: var(--muted);
      font-size: 0.98rem;
    }

    .section-tools {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
    }

    .segmented {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: flex-end;
    }

    .seg-btn {
      border: 1px solid rgba(74, 62, 48, 0.12);
      background: rgba(255, 255, 255, 0.72);
      color: var(--muted);
      border-radius: 999px;
      padding: 7px 12px;
      font: inherit;
      font-size: 0.82rem;
      letter-spacing: 0.04em;
      cursor: pointer;
      transition: background 120ms ease, color 120ms ease, border-color 120ms ease, transform 120ms ease;
    }

    .seg-btn:hover {
      transform: translateY(-1px);
      border-color: rgba(74, 62, 48, 0.22);
    }

    .seg-btn.active {
      background: var(--ink);
      color: #fff8f0;
      border-color: var(--ink);
    }

    .seg-btn:disabled {
      opacity: 0.42;
      cursor: not-allowed;
      transform: none;
    }

    .pressure-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 14px;
    }

    .storage-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
    }

    .pressure-item,
    .card,
    .kv,
    .sensor-chip,
    .process-box,
    .storage-box,
    .bar-row {
      background: var(--panel-2);
      border: 1px solid rgba(74, 62, 48, 0.08);
      border-radius: 18px;
    }

    .pressure-item {
      padding: 16px;
    }

    .pressure-label,
    .table-head,
    .small-head {
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.10em;
    }

    .pressure-value {
      font-size: 1.68rem;
      font-weight: 760;
      margin: 8px 0 10px;
    }

    .bar {
      height: 11px;
      background: rgba(52, 60, 73, 0.08);
      border-radius: 999px;
      overflow: hidden;
    }

    .bar > span {
      display: block;
      height: 100%;
      border-radius: 999px;
    }

    .storage-box {
      padding: 16px;
      min-width: 0;
    }

    .bar-list {
      display: grid;
      gap: 10px;
      margin-top: 10px;
    }

    .bar-row {
      padding: 11px 12px;
      min-width: 0;
    }

    .bar-meta {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: baseline;
      margin-bottom: 8px;
      min-width: 0;
    }

    .bar-label {
      font-size: 0.92rem;
      font-weight: 650;
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .bar-value {
      color: var(--muted);
      font-size: 0.88rem;
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .bar-track {
      height: 10px;
      border-radius: 999px;
      background: rgba(52, 60, 73, 0.08);
      overflow: hidden;
    }

    .bar-track > span {
      display: block;
      height: 100%;
      border-radius: 999px;
    }

    .bar-path {
      margin-top: 7px;
      color: var(--muted);
      font-size: 0.79rem;
      line-height: 1.35;
      word-break: break-word;
    }

    .runner-list {
      display: grid;
      gap: 10px;
      margin-top: 10px;
      min-width: 0;
    }

    .runner-row {
      padding: 11px 12px;
      background: var(--panel-2);
      border: 1px solid rgba(74, 62, 48, 0.08);
      border-radius: 18px;
      min-width: 0;
    }

    .runner-top {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      min-width: 0;
    }

    .runner-label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 0.92rem;
      font-weight: 660;
      min-width: 0;
      flex: 1 1 auto;
      overflow-wrap: anywhere;
    }

    .runner-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      flex: 0 0 auto;
    }

    .runner-meta {
      color: var(--muted);
      font-size: 0.82rem;
      text-align: right;
      flex: 0 1 8rem;
    }

    .runner-sub {
      margin-top: 7px;
      color: var(--muted);
      font-size: 0.80rem;
      line-height: 1.4;
      overflow-wrap: anywhere;
    }

    .runner-swimlane-shell {
      margin-top: 18px;
      padding: 20px;
      border-radius: 22px;
      background:
        radial-gradient(circle at top left, rgba(193, 122, 40, 0.18), transparent 28%),
        radial-gradient(circle at bottom right, rgba(74, 131, 177, 0.16), transparent 34%),
        linear-gradient(135deg, rgba(255, 249, 240, 0.96), rgba(244, 239, 232, 0.92));
      border: 1px solid rgba(74, 62, 48, 0.10);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.62),
        0 18px 40px rgba(88, 69, 47, 0.08);
      position: relative;
      overflow: hidden;
    }

    .runner-swimlane-shell::before {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(115deg, rgba(255, 255, 255, 0.00), rgba(255, 255, 255, 0.24), rgba(255, 255, 255, 0.00));
      transform: translateX(-100%);
      animation: swimlaneShellSweep 14s linear infinite;
      pointer-events: none;
      opacity: 0.6;
    }

    .runner-swimlane-title {
      font-size: 1.12rem;
      font-weight: 780;
      margin-bottom: 6px;
      letter-spacing: 0.01em;
    }

    .runner-swimlane-note {
      color: var(--muted);
      font-size: 0.94rem;
      margin-bottom: 14px;
    }

    .runner-swimlane-axis {
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      gap: 10px;
      align-items: end;
      margin-bottom: 6px;
    }

    .runner-swimlane-axis .axis-track {
      position: relative;
      height: 20px;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(74, 62, 48, 0.06), rgba(74, 62, 48, 0.02));
      border: 1px solid rgba(74, 62, 48, 0.05);
      overflow: hidden;
    }

    .runner-swimlane-axis .axis-track::before {
      content: "";
      position: absolute;
      inset: 0;
      background-image: repeating-linear-gradient(90deg, rgba(74, 62, 48, 0.10) 0, rgba(74, 62, 48, 0.10) 1px, transparent 1px, transparent 25%);
      opacity: 0.6;
    }

    .runner-swimlane-axis .axis-label {
      position: absolute;
      top: 2px;
      transform: translateX(-50%);
      font-size: 0.64rem;
      color: var(--muted);
      white-space: nowrap;
    }

    .runner-swimlane-groups {
      display: grid;
      gap: 10px;
    }

    .runner-swimlane-section {
      padding: 12px;
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(255, 252, 246, 0.90), rgba(251, 247, 241, 0.76));
      border: 1px solid rgba(74, 62, 48, 0.08);
      min-width: 0;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
    }

    .runner-swimlane-section-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 10px;
      min-width: 0;
    }

    .runner-swimlane-section-title {
      font-size: 0.92rem;
      font-weight: 760;
      letter-spacing: 0.02em;
    }

    .runner-swimlane-section-note {
      color: var(--muted);
      font-size: 0.87rem;
      text-align: right;
    }

    .runner-swimlane-board {
      display: grid;
      gap: 8px;
    }

    .runner-swimlane-row {
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      gap: 10px;
      align-items: stretch;
      min-width: 0;
    }

    .runner-swimlane-label {
      min-width: 0;
      padding: 6px 8px;
      border-radius: 12px;
      background: linear-gradient(180deg, rgba(250, 246, 240, 0.96), rgba(242, 237, 230, 0.82));
      border: 1px solid rgba(74, 62, 48, 0.08);
      box-shadow: 0 8px 20px rgba(89, 70, 47, 0.05);
      transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
    }

    .runner-swimlane-row:hover .runner-swimlane-label {
      transform: translateY(-1px);
      box-shadow: 0 14px 28px rgba(89, 70, 47, 0.09);
      border-color: rgba(193, 122, 40, 0.22);
    }

    .runner-swimlane-name {
      font-size: 0.92rem;
      font-weight: 760;
      line-height: 1.1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .runner-swimlane-sub {
      margin-top: 1px;
      color: var(--muted);
      font-size: 0.64rem;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }

    .runner-swimlane-track {
      position: relative;
      min-height: 46px;
      border-radius: 14px;
      border: 1px solid rgba(74, 62, 48, 0.10);
      background:
        radial-gradient(circle at left center, rgba(193, 122, 40, 0.08), transparent 24%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(245, 241, 235, 0.98)),
        linear-gradient(90deg, rgba(74, 62, 48, 0.02), rgba(74, 62, 48, 0.00));
      overflow: hidden;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), inset 0 -10px 22px rgba(91, 73, 51, 0.04);
    }

    .runner-swimlane-track::before {
      content: "";
      position: absolute;
      inset: 0;
      background-image: repeating-linear-gradient(90deg, rgba(74, 62, 48, 0.08) 0, rgba(74, 62, 48, 0.08) 1px, transparent 1px, transparent 12.5%);
      opacity: 0.45;
      pointer-events: none;
    }

    .runner-swimlane-track::selection {
      background: transparent;
    }

    .runner-swimlane-track::after {
      content: "";
      position: absolute;
      top: 0;
      right: 0;
      width: 14px;
      height: 100%;
      background: linear-gradient(90deg, rgba(255, 255, 255, 0), rgba(247, 244, 238, 0.96));
      pointer-events: none;
    }

    .runner-swimlane-block,
    .runner-swimlane-mark {
      position: absolute;
      top: 4px;
      bottom: 4px;
      border-radius: 10px;
      box-shadow: 0 12px 28px rgba(61, 50, 37, 0.14);
      overflow: hidden;
      transition: left 980ms linear, width 980ms linear, transform 220ms ease, box-shadow 220ms ease, filter 220ms ease;
      cursor: pointer;
      will-change: left, width, transform;
    }

    .runner-swimlane-block {
      padding: 2px 6px;
      color: #fff8f0;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 0;
      border: 1px solid rgba(255, 255, 255, 0.16);
      background-size: 160% 160%;
      animation: swimlaneBlockRise 560ms ease both, swimlaneBlockPulse 8s ease-in-out infinite;
    }

    .runner-swimlane-mark {
      width: 8px;
      min-width: 8px;
      padding: 0;
      border: 1px solid rgba(255, 255, 255, 0.18);
      animation: swimlaneMarkIn 420ms ease both;
    }

    .runner-swimlane-row:hover .runner-swimlane-block,
    .runner-swimlane-row:hover .runner-swimlane-mark {
      transform: translateY(-2px);
      box-shadow: 0 18px 34px rgba(61, 50, 37, 0.18);
      filter: saturate(1.08);
    }

    .runner-swimlane-block.event-live {
      background-image: linear-gradient(135deg, #2f8a73, #4aa38f 45%, #6dc2b1 100%);
    }

    .runner-swimlane-block.event-run {
      background-image: linear-gradient(135deg, #6d5fc2, #8b75dd 48%, #b09aed 100%);
    }

    .runner-swimlane-mark.start {
      border-radius: 14px 8px 8px 14px;
      background: linear-gradient(180deg, #f0a43a, #d27a21);
      box-shadow: 0 0 0 1px rgba(255, 245, 230, 0.35), 0 0 18px rgba(210, 122, 33, 0.25);
    }

    .runner-swimlane-mark.stop {
      border-radius: 8px 14px 14px 8px;
      background: linear-gradient(180deg, #db6f66, #b9534c);
      box-shadow: 0 0 0 1px rgba(255, 238, 235, 0.35), 0 0 18px rgba(185, 83, 76, 0.22);
    }

    .runner-swimlane-block .swimlane-head {
      font-size: 0.70rem;
      font-weight: 760;
      overflow-wrap: anywhere;
      line-height: 1.1;
      text-shadow: 0 1px 8px rgba(18, 16, 12, 0.22);
    }

    .runner-swimlane-block .swimlane-meta {
      display: none;
    }

    .runner-swimlane-block .swimlane-chip {
      position: absolute;
      top: 3px;
      right: 5px;
      padding: 1px 5px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.14);
      font-size: 0.50rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .runner-swimlane-track .swimlane-now {
      position: absolute;
      top: 0;
      bottom: 0;
      right: 0;
      width: 2px;
      background: rgba(47, 138, 115, 0.86);
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.68), 0 0 20px rgba(47, 138, 115, 0.34);
      animation: swimlaneNowPulse 2.6s ease-in-out infinite;
    }

    .runner-swimlane-track .swimlane-now::after {
      content: "now";
      position: absolute;
      top: -8px;
      right: 0;
      transform: translate(50%, -100%);
      font-size: 0.66rem;
      color: rgba(47, 138, 115, 0.86);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .runner-swimlane-empty {
      color: var(--muted);
      font-size: 0.90rem;
      padding: 10px 2px;
    }

    @keyframes swimlaneShellSweep {
      0% { transform: translateX(-100%); }
      100% { transform: translateX(140%); }
    }

    @keyframes swimlaneBlockRise {
      0% { opacity: 0; transform: translateY(8px) scale(0.98); }
      100% { opacity: 1; transform: translateY(0) scale(1); }
    }

    @keyframes swimlaneBlockPulse {
      0%, 100% { background-position: 0% 50%; }
      50% { background-position: 100% 50%; }
    }

    @keyframes swimlaneMarkIn {
      0% { opacity: 0; transform: scaleY(0.7); }
      100% { opacity: 1; transform: scaleY(1); }
    }

    @keyframes swimlaneNowPulse {
      0%, 100% { opacity: 0.72; box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.68), 0 0 12px rgba(47, 138, 115, 0.24); }
      50% { opacity: 1; box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.74), 0 0 24px rgba(47, 138, 115, 0.42); }
    }

    .cards {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }

    .card {
      padding: 18px;
      min-height: 136px;
    }

    .card h2 {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 0.86rem;
      text-transform: uppercase;
      letter-spacing: 0.10em;
    }

    .value {
      font-size: 2rem;
      font-weight: 780;
      margin-bottom: 8px;
    }

    .detail {
      color: var(--muted);
      font-size: 0.98rem;
      line-height: 1.55;
    }

    .visual-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      margin-bottom: 18px;
    }

    .chart-panel,
    .process-panel,
    .inventory {
      padding: 22px;
      min-width: 0;
    }

    .visual-grid .wide {
      grid-column: span 2;
    }

    svg {
      width: 100%;
      height: auto;
      display: block;
      overflow: hidden;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.66);
      border: 1px solid rgba(74, 62, 48, 0.08);
    }

    .chart-tooltip {
      position: fixed;
      z-index: 50;
      display: none;
      pointer-events: none;
      max-width: 340px;
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(29, 26, 22, 0.96);
      color: #fff8f0;
      box-shadow: 0 16px 36px rgba(29, 26, 22, 0.22);
      border: 1px solid rgba(255, 255, 255, 0.08);
      backdrop-filter: blur(10px);
      font-size: 0.82rem;
      line-height: 1.42;
    }

    .chart-tooltip .tt-title {
      font-size: 0.64rem;
      font-weight: 740;
      margin-bottom: 6px;
      letter-spacing: 0.02em;
    }

    .chart-tooltip .tt-muted {
      color: rgba(255, 248, 240, 0.74);
      margin-bottom: 6px;
    }

    .chart-tooltip .tt-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
    }

    .chart-tooltip .tt-row + .tt-row {
      margin-top: 4px;
    }

    .chart-tooltip .tt-name {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .chart-tooltip .tt-swatch {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      flex: 0 0 auto;
      margin-top: 1px;
    }

    .chart-tooltip .tt-value {
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
      flex: 0 0 auto;
    }

    #process-table-wrap {
      width: 100%;
      max-width: 100%;
      min-width: 0;
      overflow-x: auto;
    }

    #process-table-wrap table {
      width: 100%;
      min-width: 0;
      table-layout: fixed;
    }

    #process-table-wrap th,
    #process-table-wrap td {
      padding-left: 6px;
      padding-right: 6px;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .sensor-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 10px;
    }

    .sensor-chip {
      padding: 12px;
    }

    .sensor-value {
      font-size: 1.35rem;
      font-weight: 740;
      margin-top: 6px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.94rem;
    }

    th,
    td {
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid rgba(74, 62, 48, 0.08);
    }

    th {
      color: var(--muted);
      font-size: 0.80rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .inventory-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .kv {
      padding: 14px;
    }

    .kv .k {
      color: var(--muted);
      font-size: 0.80rem;
      text-transform: uppercase;
      letter-spacing: 0.10em;
      margin-bottom: 6px;
    }

    .kv .v {
      font-size: 0.98rem;
      line-height: 1.46;
      word-break: break-word;
    }

    @media (max-width: 1200px) {
      .hero { grid-template-columns: 1fr; }
      .cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .inventory-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .storage-grid { grid-template-columns: 1fr; }
    }

    @media (max-width: 960px) {
      .visual-grid { grid-template-columns: 1fr; }
      .visual-grid .wide { grid-column: span 1; }
      .pressure-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .headline-grid { grid-template-columns: 1fr; }
      .dashboard-tabs {
        position: static;
        align-items: flex-start;
        flex-direction: column;
      }
      .dashboard-tab-note {
        white-space: normal;
      }
      .tab-list {
        justify-content: flex-start;
      }
      .bar-meta { flex-wrap: wrap; }
      .bar-value { white-space: normal; }
      .runner-swimlane-axis,
      .runner-swimlane-row {
        grid-template-columns: minmax(104px, 26vw) minmax(0, 1fr);
      }
      .runner-swimlane-axis .axis-track,
      .runner-swimlane-track {
        min-width: 0;
      }
      .runner-swimlane-section-head {
        flex-direction: column;
        align-items: flex-start;
      }
      .runner-swimlane-section-note {
        text-align: left;
      }
    }

    @media (max-width: 700px) {
      .wrap { padding: 18px 14px 32px; }
      .cards,
      .pressure-grid,
      .inventory-grid { grid-template-columns: 1fr; }
      .hero-main,
      .hero-side,
      .chart-panel,
      .process-panel,
      .inventory,
      .pressure { padding: 20px; }
      .section-tools,
      .segmented { justify-content: flex-start; }
      .runner-top { flex-direction: column; }
      .runner-meta { text-align: left; flex-basis: auto; }
      .runner-swimlane-shell,
      .runner-swimlane-section { padding: 10px; }
      .runner-swimlane-label { padding: 6px 8px; }
      .runner-swimlane-track { min-height: 46px; }
    }
  </style>
</head>
<body data-active-page="overview">
  <div class="wrap">
    <section class="hero">
      <article class="panel hero-main">
        <div class="eyebrow">Remote Ops Console</div>
        <h1>tiny-m73 operations deck</h1>
        <div class="hero-copy">Live operations telemetry for worker lanes, host admission queue, CPU, memory, swap, disk, load, thermal zones, network throughput, pressure actors, and hardware diagnostics. Built for triage, not screenshots.</div>
        <div class="hero-meta" id="hero-meta">Connecting…</div>
        <div class="headline-grid" id="headline-grid"></div>
      </article>
      <article class="panel hero-side">
        <div class="temp-row">
          <div class="temp-big" id="temp-big">--.-C</div>
          <div class="badge steady" id="status-badge">loading</div>
        </div>
        <div class="detail" id="hero-side-copy">Waiting for the first collector sample.</div>
        <ul class="diag-list" id="diag-list"></ul>
      </article>
    </section>

    <section class="alert-rail" id="alert-rail"></section>

    <section class="panel pressure">
      <div class="section-head">
        <div class="section-title">Pressure Strip</div>
        <div class="section-note" id="pressure-note"></div>
      </div>
      <div class="pressure-grid" id="pressure-grid"></div>
    </section>

    <section class="cards" id="cards"></section>

    <section class="panel history-panel">
      <div class="section-head">
        <div>
          <div class="section-title">History Window</div>
          <div class="section-note" id="history-note">Applies the same window to the current tab</div>
        </div>
        <div class="section-tools">
          <div class="segmented" id="history-range"></div>
        </div>
      </div>
    </section>

    <nav class="panel dashboard-tabs" aria-label="Dashboard pages">
      <div class="dashboard-tab-copy">
        <div class="dashboard-tab-title">Pages</div>
        <div class="dashboard-tab-note" id="dashboard-tab-note">Overview panels are visible.</div>
      </div>
      <div class="tab-list" id="dashboard-tabs" role="tablist">
        <button class="tab-btn active" type="button" data-page="overview" role="tab" aria-selected="true">Overview</button>
        <button class="tab-btn" type="button" data-page="workers" role="tab" aria-selected="false">Workers</button>
        <button class="tab-btn" type="button" data-page="host" role="tab" aria-selected="false">Host</button>
        <button class="tab-btn" type="button" data-page="storage" role="tab" aria-selected="false">Storage</button>
        <button class="tab-btn" type="button" data-page="diagnostics" role="tab" aria-selected="false">Diagnostics</button>
      </div>
    </nav>

    <section class="visual-grid">
      <article class="panel chart-panel wide tabbed-panel" data-pages="host">
        <div class="section-head">
          <div>
            <div class="section-title">CPU Fabric</div>
            <div class="section-note" id="heatmap-note">Per-core utilization heatmap across the recent sample window</div>
          </div>
        </div>
        <svg id="core-heatmap" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="overview host">
        <div class="section-head">
          <div class="section-title">Thermal Manifold</div>
          <div class="section-note" id="thermal-note">Package and exposed thermal zones</div>
        </div>
        <svg id="thermal-chart" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="overview host">
        <div class="section-head">
          <div class="section-title">System Pressure And Thermals</div>
          <div class="section-note">Total CPU, hottest core, package temp, RAM, swap, and disk usage</div>
        </div>
        <svg id="pressure-chart" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="host">
        <div class="section-head">
          <div class="section-title">Scheduler And Throughput</div>
          <div class="section-note">Load per core, receive, and transmit rate</div>
        </div>
        <svg id="ops-chart" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="workers">
        <div class="section-head">
          <div>
            <div class="section-title">Disk Cadence And Worker Flow</div>
            <div class="section-note" id="disk-io-note">Read and write throughput, disk busy, and worker-lane activity overlays</div>
          </div>
        </div>
        <svg id="disk-io-chart" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
        <div class="runner-swimlane-shell">
          <div class="runner-swimlane-title">Worker Swimlanes</div>
          <div class="runner-swimlane-note" id="runner-swimlane-note">Worker-lane board across the current history window.</div>
          <div class="runner-swimlane-axis" id="runner-swimlane-axis"></div>
          <div class="runner-swimlane-groups">
            <section class="runner-swimlane-section">
              <div class="runner-swimlane-section-head">
                <div class="runner-swimlane-section-title">Active Worker Lanes</div>
                <div class="runner-swimlane-section-note" id="active-runner-note">No live worker lanes yet.</div>
              </div>
              <div class="runner-swimlane-board" id="active-runner-list"></div>
            </section>
            <section class="runner-swimlane-section">
              <div class="runner-swimlane-section-head">
                <div class="runner-swimlane-section-title">Recent Lane History</div>
                <div class="runner-swimlane-section-note" id="recent-runner-note">Completed and idle lanes in the current window; live lanes are shown above.</div>
              </div>
              <div class="runner-swimlane-board" id="recent-runner-events"></div>
            </section>
          </div>
        </div>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="workers">
        <div class="section-head">
          <div>
            <div class="section-title">Worker Fabric</div>
            <div class="section-note" id="worker-note">Worker-lane occupancy, saturation, and live lease claims</div>
          </div>
        </div>
        <svg id="worker-chart" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
        <div class="storage-grid">
          <div class="storage-box">
            <div class="table-head">Workers</div>
            <div class="bar-list" id="worker-breakdown"></div>
          </div>
          <div class="storage-box">
            <div class="table-head">Active Lanes</div>
            <div class="runner-list" id="worker-lane-list"></div>
          </div>
        </div>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="workers">
        <div class="section-head">
          <div>
            <div class="section-title">Queue Pressure And Flow</div>
            <div class="section-note" id="queue-note">host admission occupancy, waiter age, and queue transitions</div>
          </div>
        </div>
        <svg id="queue-chart" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
        <div class="storage-grid">
          <div class="storage-box">
            <div class="table-head">Current Holders</div>
            <div class="runner-list" id="queue-holder-list"></div>
          </div>
          <div class="storage-box">
            <div class="table-head">Current Waiters</div>
            <div class="runner-list" id="queue-waiter-list"></div>
          </div>
        </div>
        <div class="storage-grid">
          <div class="storage-box">
            <div class="table-head">Queue Reason Mix</div>
            <div class="bar-list" id="queue-reason-breakdown"></div>
          </div>
          <div class="storage-box">
            <div class="table-head">Recent Queue Events</div>
            <div class="runner-list" id="queue-event-list"></div>
          </div>
        </div>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="storage">
        <div class="section-head">
          <div class="section-title">Storage Runway</div>
          <div class="section-note" id="storage-note">Root usage history, reclaim events, and current storage topology</div>
        </div>
        <svg id="storage-chart" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
        <div class="storage-grid">
          <div class="storage-box">
            <div class="table-head">Current Footprint</div>
            <div class="bar-list" id="storage-breakdown"></div>
          </div>
          <div class="storage-box">
            <div class="table-head">Worker Namespaces</div>
            <div class="bar-list" id="namespace-breakdown"></div>
          </div>
        </div>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="diagnostics storage">
        <div class="section-head">
          <div class="section-title">Pressure Actors Trail</div>
          <div class="section-note" id="process-trend-note">Dominant process pressure over the recent history window</div>
        </div>
        <svg id="process-trend-chart" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMid meet"></svg>
      </article>

      <article class="panel chart-panel wide tabbed-panel" data-pages="overview host diagnostics">
        <div class="section-head">
          <div class="section-title">Live Thermal Sensors</div>
          <div class="section-note">Current package and zone readings</div>
        </div>
        <div class="sensor-grid" id="sensor-grid"></div>
      </article>

      <article class="panel process-panel tabbed-panel" data-pages="diagnostics">
        <div class="section-head">
          <div class="section-title">Pressure Actors</div>
          <div class="section-note">Processes ranked by swap and resident footprint</div>
        </div>
        <div id="process-table-wrap"></div>
      </article>
    </section>

    <section class="panel inventory tabbed-panel" data-pages="diagnostics">
      <div class="section-head">
        <div class="section-title">Hardware And Diag Info</div>
        <div class="section-note" id="inventory-note"></div>
      </div>
      <div class="inventory-grid" id="inventory-grid"></div>
    </section>
  </div>

  <div class="chart-tooltip" id="chart-tooltip" aria-hidden="true"></div>

  <script>
    const alertRailEl = document.getElementById("alert-rail");
    const pressureGrid = document.getElementById("pressure-grid");
    const cardsEl = document.getElementById("cards");
    const heroMetaEl = document.getElementById("hero-meta");
    const heroSideCopyEl = document.getElementById("hero-side-copy");
    const tempBigEl = document.getElementById("temp-big");
    const statusBadgeEl = document.getElementById("status-badge");
    const diagListEl = document.getElementById("diag-list");
    const pressureNoteEl = document.getElementById("pressure-note");
    const inventoryGridEl = document.getElementById("inventory-grid");
    const inventoryNoteEl = document.getElementById("inventory-note");
    const thermalNoteEl = document.getElementById("thermal-note");
    const sensorGridEl = document.getElementById("sensor-grid");
    const processTableWrapEl = document.getElementById("process-table-wrap");
    const heatmapNoteEl = document.getElementById("heatmap-note");
    const historyNoteEl = document.getElementById("history-note");
    const historyRangeEl = document.getElementById("history-range");
    const diskIoNoteEl = document.getElementById("disk-io-note");
    const workerNoteEl = document.getElementById("worker-note");
    const workerBreakdownEl = document.getElementById("worker-breakdown");
    const workerLaneListEl = document.getElementById("worker-lane-list");
    const storageNoteEl = document.getElementById("storage-note");
    const storageBreakdownEl = document.getElementById("storage-breakdown");
    const namespaceBreakdownEl = document.getElementById("namespace-breakdown");
    const activeRunnerListEl = document.getElementById("active-runner-list");
    const recentRunnerEventsEl = document.getElementById("recent-runner-events");
    const queueNoteEl = document.getElementById("queue-note");
    const queueHolderListEl = document.getElementById("queue-holder-list");
    const queueWaiterListEl = document.getElementById("queue-waiter-list");
    const queueReasonBreakdownEl = document.getElementById("queue-reason-breakdown");
    const queueEventListEl = document.getElementById("queue-event-list");
    const processTrendNoteEl = document.getElementById("process-trend-note");
    const headlineGridEl = document.getElementById("headline-grid");
    const chartTooltipEl = document.getElementById("chart-tooltip");
    const runnerSwimlaneAxisEl = document.getElementById("runner-swimlane-axis");
    const runnerSwimlaneNoteEl = document.getElementById("runner-swimlane-note");
    const activeRunnerNoteEl = document.getElementById("active-runner-note");
    const recentRunnerNoteEl = document.getElementById("recent-runner-note");
    const dashboardTabsEl = document.getElementById("dashboard-tabs");
    const dashboardTabNoteEl = document.getElementById("dashboard-tab-note");
    let lastPayload = null;
    let resizeTimer = null;
    let storageWarmTimer = null;
    const historyWindows = [
      { label: "30m", minutes: 30 },
      { label: "2h", minutes: 120 },
      { label: "6h", minutes: 360 },
      { label: "12h", minutes: 720 },
      { label: "All", minutes: null },
    ];
    let historyWindowMinutes = 120;
    const dashboardPages = {
      overview: "Key pressure, thermal, and sensor panels are visible.",
      workers: "Worker lanes, queue flow, and admission detail are visible.",
      host: "CPU, scheduler, throughput, and host thermals are visible.",
      storage: "Disk runway, namespace footprint, and process pressure trail are visible.",
      diagnostics: "Hardware inventory, thermal sensors, and pressure actors are visible.",
    };

    function setActiveDashboardPage(page, options = {}) {
      const nextPage = dashboardPages[page] ? page : "overview";
      document.body.dataset.activePage = nextPage;
      if (dashboardTabNoteEl) dashboardTabNoteEl.textContent = dashboardPages[nextPage];
      if (dashboardTabsEl) {
        [...dashboardTabsEl.querySelectorAll(".tab-btn")].forEach((button) => {
          const active = button.dataset.page === nextPage;
          button.classList.toggle("active", active);
          button.setAttribute("aria-selected", active ? "true" : "false");
        });
      }
      if (options.persist !== false) {
        try { localStorage.setItem("tiny-m73-dashboard-page", nextPage); } catch (_) {}
      }
      if (options.rerender !== false && lastPayload) render(lastPayload);
    }

    function initDashboardTabs() {
      let initialPage = "overview";
      try { initialPage = localStorage.getItem("tiny-m73-dashboard-page") || initialPage; } catch (_) {}
      setActiveDashboardPage(initialPage, { persist: false, rerender: false });
      if (!dashboardTabsEl) return;
      dashboardTabsEl.addEventListener("click", (event) => {
        const button = event.target.closest(".tab-btn");
        if (!button) return;
        setActiveDashboardPage(button.dataset.page || "overview");
      });
    }

    function chartIsVisible(svgId) {
      const svg = document.getElementById(svgId);
      const panel = svg?.closest(".tabbed-panel");
      return !panel || getComputedStyle(panel).display !== "none";
    }

    function drawVisible(svgId, drawFn) {
      if (chartIsVisible(svgId)) drawFn();
    }

    function fmt1(value) {
      return `${value.toFixed(1)}`;
    }

    function fmtPct(value) {
      return `${value.toFixed(1)}%`;
    }

    function fmtGib(value) {
      return `${value.toFixed(1)} GiB`;
    }

    function fmtMib(value) {
      return `${value.toFixed(1)} MiB`;
    }

    function fmtMibRate(value) {
      return `${value.toFixed(value < 1 ? 2 : 1)} MiB/s`;
    }

    function fmtIops(value) {
      return `${value.toFixed(value < 10 ? 1 : 0)} IOPS`;
    }

    function fmtTime(iso) {
      const d = new Date(iso);
      return d.toLocaleString([], {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }

    function fmtClock(value) {
      const d = new Date(value);
      return d.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }

    function fmtSpan(ms) {
      if (!Number.isFinite(ms) || ms < 0) return "n/a";
      const totalSeconds = Math.round(ms / 1000);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      if (hours > 0) return `${hours}h ${minutes}m`;
      if (minutes > 0) return `${minutes}m ${seconds}s`;
      return `${seconds}s`;
    }

    function statusText(status) {
      if (status === "attention") return "Attention";
      if (status === "busy") return "Busy";
      return "Steady";
    }

    function shortText(value, max = 28) {
      if (!value || value.length <= max) return value || "";
      return `${value.slice(0, max - 1)}…`;
    }

    function runnerColor(label) {
      if ((label || "").startsWith("codex-b/")) return "#6d5fc2";
      if ((label || "").startsWith("ns/")) return "#4a83b1";
      return "#b55c2f";
    }

    function runnerEventColor(kind) {
      return kind === "stop" ? "#9a5b55" : "#2f8a73";
    }

    function queueEventColor(kind) {
      if (kind === "queued") return "#c17a28";
      if (kind === "acquired") return "#2f8a73";
      if (kind === "released") return "#9a5b55";
      if (kind === "dequeued") return "#6d5fc2";
      return "#4a83b1";
    }

    function colorForSensor(sensor) {
      if (sensor.kind === "package") return "var(--temp)";
      if (sensor.kind === "core") return "var(--zone)";
      return "#8d8d76";
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[ch]));
    }

    function chartTitleForSvg(svg, fallback = "") {
      return svg.closest(".chart-panel")?.querySelector(".section-title")?.textContent?.trim() || fallback;
    }

    function hideChartTooltip() {
      if (!chartTooltipEl) return;
      chartTooltipEl.style.display = "none";
      chartTooltipEl.setAttribute("aria-hidden", "true");
    }

    function showChartTooltip(html, clientX, clientY) {
      if (!chartTooltipEl) return;
      chartTooltipEl.innerHTML = html;
      chartTooltipEl.style.display = "block";
      chartTooltipEl.style.visibility = "hidden";
      const pad = 12;
      const offset = 16;
      let left = clientX + offset;
      let top = clientY + offset;
      const rect = chartTooltipEl.getBoundingClientRect();
      if (left + rect.width > window.innerWidth - pad) {
        left = clientX - rect.width - offset;
      }
      if (top + rect.height > window.innerHeight - pad) {
        top = clientY - rect.height - offset;
      }
      chartTooltipEl.style.left = `${Math.max(pad, left)}px`;
      chartTooltipEl.style.top = `${Math.max(pad, top)}px`;
      chartTooltipEl.style.visibility = "visible";
      chartTooltipEl.setAttribute("aria-hidden", "false");
    }

    function buildTooltipHtml(title, subtitle, rows) {
      const body = rows.map((row) => `<div class="tt-row"><div class="tt-name"><span class="tt-swatch" style="background:${row.color}"></span>${escapeHtml(row.name)}</div><div class="tt-value">${escapeHtml(row.value)}</div></div>`).join("");
      return `<div class="tt-title">${escapeHtml(title)}</div>${subtitle ? `<div class="tt-muted">${escapeHtml(subtitle)}</div>` : ""}${body}`;
    }

    function swimlaneTooltipData(title, subtitle, rows) {
      return encodeURIComponent(buildTooltipHtml(title, subtitle, rows));
    }

    function nearestPoint(points, targetX) {
      let best = null;
      let bestDistance = Infinity;
      points.forEach((point) => {
        const distance = Math.abs(point.x - targetX);
        if (distance < bestDistance) {
          best = point;
          bestDistance = distance;
        }
      });
      return best;
    }

    function bindLineTooltip(svg, state) {
      svg.__tooltipState = state;
      if (svg.__lineTooltipBound) return;
      svg.__lineTooltipBound = true;
      svg.style.cursor = "crosshair";
      const update = (event) => {
        const current = svg.__tooltipState;
        if (!current || !current.lines || !current.lines.length) {
          hideChartTooltip();
          return;
        }
        const rect = svg.getBoundingClientRect();
        if (!rect.width || !rect.height) {
          hideChartTooltip();
          return;
        }
        const x = ((event.clientX - rect.left) / rect.width) * current.width;
        const y = ((event.clientY - rect.top) / rect.height) * current.height;
        if (x < current.left || x > current.width - current.right || y < current.top || y > current.height - current.bottom) {
          hideChartTooltip();
          return;
        }
        const allPoints = current.lines.flatMap((line) => line.points);
        const anchor = nearestPoint(allPoints, current.minX + ((x - current.left) / Math.max(1, current.plotWidth)) * current.spanX);
        if (!anchor) {
          hideChartTooltip();
          return;
        }
        const rows = current.lines.map((line) => {
          const point = nearestPoint(line.points, anchor.x);
          if (!point) return null;
          const value = typeof line.tooltip === "function"
            ? line.tooltip(point, anchor)
            : (point.y == null ? "n/a" : point.y.toFixed(1));
          return { color: line.color, name: line.name, value };
        }).filter(Boolean);
        if (!rows.length) {
          hideChartTooltip();
          return;
        }
        showChartTooltip(buildTooltipHtml(current.title || "Chart", fmtTime(new Date(anchor.x).toISOString()), rows), event.clientX, event.clientY);
      };
      svg.addEventListener("pointerenter", update);
      svg.addEventListener("pointermove", update);
      svg.addEventListener("pointerleave", hideChartTooltip);
      svg.addEventListener("pointercancel", hideChartTooltip);
      svg.addEventListener("mouseenter", update);
      svg.addEventListener("mousemove", update);
      svg.addEventListener("mouseleave", hideChartTooltip);
    }

    function bindHeatmapTooltip(svg, state) {
      svg.__heatmapTooltipState = state;
      if (svg.__heatmapTooltipBound) return;
      svg.__heatmapTooltipBound = true;
      svg.style.cursor = "crosshair";
      const update = (event) => {
        const current = svg.__heatmapTooltipState;
        if (!current || !current.samples || !current.samples.length || !current.cores || !current.cores.length) {
          hideChartTooltip();
          return;
        }
        const rect = svg.getBoundingClientRect();
        if (!rect.width || !rect.height) {
          hideChartTooltip();
          return;
        }
        const x = ((event.clientX - rect.left) / rect.width) * current.width;
        const y = ((event.clientY - rect.top) / rect.height) * current.height;
        if (x < current.left || x > current.width - current.right || y < current.top || y > current.height - current.bottom) {
          hideChartTooltip();
          return;
        }
        const column = Math.min(current.samples.length - 1, Math.max(0, Math.floor((x - current.left) / Math.max(1, current.cellWidth))));
        const row = Math.min(current.cores.length - 1, Math.max(0, Math.floor((y - current.top) / Math.max(1, current.cellHeight))));
        const sample = current.samples[column];
        const core = current.cores[row];
        const value = sample?.per_core_pct?.[core];
        if (value == null) {
          hideChartTooltip();
          return;
        }
        const color = current.colorForValue ? current.colorForValue(value) : "#2f8a73";
        showChartTooltip(buildTooltipHtml(current.title || "CPU Fabric", `${core} · ${fmtTime(new Date(sample.timestamp).toISOString())}`, [
          { color, name: "Utilization", value: fmtPct(value) },
        ]), event.clientX, event.clientY);
      };
      svg.addEventListener("pointerenter", update);
      svg.addEventListener("pointermove", update);
      svg.addEventListener("pointerleave", hideChartTooltip);
      svg.addEventListener("pointercancel", hideChartTooltip);
    }

    function bindSwimlaneTooltips(container) {
      if (!container || container.__swimlaneTooltipBound) return;
      container.__swimlaneTooltipBound = true;
      const update = (event) => {
        const el = event.target.closest("[data-tooltip-html]");
        if (!el || !container.contains(el)) {
          hideChartTooltip();
          return;
        }
        const html = el.dataset.tooltipHtml ? decodeURIComponent(el.dataset.tooltipHtml) : "";
        if (!html) {
          hideChartTooltip();
          return;
        }
        showChartTooltip(html, event.clientX, event.clientY);
      };
      container.addEventListener("pointerenter", update, true);
      container.addEventListener("pointermove", update);
      container.addEventListener("pointerleave", hideChartTooltip);
      container.addEventListener("pointercancel", hideChartTooltip);
      container.addEventListener("mousemove", update);
      container.addEventListener("mouseleave", hideChartTooltip);
    }

    function sinceWindow(series, minutes) {
      if (!series.length) return [];
      const cutoff = new Date(series[series.length - 1].timestamp).getTime() - minutes * 60 * 1000;
      return series.filter((sample) => new Date(sample.timestamp).getTime() >= cutoff);
    }

    function avg(samples, key) {
      const values = samples.map((sample) => sample[key]).filter((value) => value !== null && value !== undefined);
      if (!values.length) return null;
      return values.reduce((sum, value) => sum + value, 0) / values.length;
    }

    function renderAlerts(payload) {
      const alerts = payload.alerts || [];
      if (!alerts.length) {
        alertRailEl.innerHTML = "";
        return;
      }
      alertRailEl.innerHTML = alerts.map((alert) => `<article class="alert-box ${alert.level || "warn"}">
        <div class="alert-head">
          <div class="alert-title">${alert.title}</div>
          <div class="alert-level">${(alert.level || "warn").toUpperCase()}</div>
        </div>
        <div class="alert-text">${alert.text}</div>
      </article>`).join("");
    }

        function renderHeadline(payload) {
      const latest = payload.latest;
      const queue = payload.queue || { lock_name: "runner-host", queue_depth: 0, active_holders: 0, capacity: 0, discovered_lock_domains: [] };
      const workers = payload.worker_state || { active_lanes: 0, total_lanes: 0, worker_count: 0, busy_worker_count: 0 };
      const oldestWaitText = queue.queue_depth ? fmtDuration(Math.max(1, Math.round((queue.oldest_waiter_seconds || 0) / 60))) : "none";
      const chips = [
        ["Worker Lanes", `${latest.active_worker_lanes || 0}/${latest.total_worker_lanes || workers.total_lanes || 0}`],
        ["Busy Workers", `${latest.busy_worker_count || 0}/${latest.worker_count || workers.worker_count || 0}`],
        ["Queue Depth", queue.queue_depth ? `${queue.queue_depth} waiting` : "empty"],
        ["Queue Holders", `${queue.active_holders}/${queue.capacity}`],
        ["Oldest Wait", oldestWaitText],
        ["Lock Domain", queue.lock_name || "n/a"],
      ];
      headlineGridEl.innerHTML = chips.map(([k, v]) => `<div class="headline-chip"><div class="chip-k">${k}</div><div class="chip-v">${v}</div></div>`).join("");
      heroMetaEl.textContent = `Updated ${fmtTime(payload.updated_at)} · history since ${fmtTime(payload.history_started_at)} · ${payload.sample_count} samples · ${payload.stale ? "stale" : "fresh"} collector`;
      heroSideCopyEl.textContent = `CPU ${latest.cpu_pct == null ? "warming up" : fmtPct(latest.cpu_pct)} · worker lanes ${latest.active_worker_lanes || 0}/${latest.total_worker_lanes || 0} · queue ${queue.queue_depth} wait / ${queue.active_holders} hold · disk ${fmtPct(latest.disk_used_pct)} · uptime ${latest.uptime_hours.toFixed(1)} h`;
      tempBigEl.textContent = latest.temp_c == null ? "n/a" : `${fmt1(latest.temp_c)}C`;
      statusBadgeEl.textContent = statusText(payload.status);
      statusBadgeEl.className = `badge ${payload.status}`;
      diagListEl.innerHTML = payload.notes.map((note) => `<li>${note}</li>`).join("");
    }

        function renderPressure(payload) {
      const latest = payload.latest;
      const queue = payload.queue || { queue_depth: 0, active_holders: 0, capacity: 1, queue_saturation_pct: 0 };
      const queueWidth = Math.max(queue.queue_saturation_pct || 0, queue.queue_depth ? Math.min(100, (queue.queue_depth / Math.max(1, queue.capacity)) * 100) : 0);
      const items = [
        { label: "CPU", value: latest.cpu_pct ?? 0, text: latest.cpu_pct == null ? "warming up" : fmtPct(latest.cpu_pct), color: "var(--cpu)", cap: 100 },
        { label: "RAM", value: latest.mem_used_pct, text: fmtPct(latest.mem_used_pct), color: "var(--mem)", cap: 100 },
        { label: "Swap", value: latest.swap_used_pct, text: fmtPct(latest.swap_used_pct), color: "var(--swap)", cap: 100 },
        { label: "Disk", value: latest.disk_used_pct, text: fmtPct(latest.disk_used_pct), color: "var(--disk)", cap: 100 },
        { label: "Temp", value: latest.temp_c ?? 0, text: latest.temp_c == null ? "n/a" : `${fmt1(latest.temp_c)}C`, color: "var(--temp)", cap: 95 },
        { label: "Workers", value: latest.worker_saturation_pct ?? 0, text: `${latest.active_worker_lanes || 0}/${latest.total_worker_lanes || 0} lanes`, color: "#c17a28", cap: 100 },
      ];
      pressureGrid.innerHTML = items.map((item) => {
        const width = Math.max(0, Math.min(100, item.value / item.cap * 100));
        return `<div class="pressure-item">
          <div class="pressure-label">${item.label}</div>
          <div class="pressure-value">${item.text}</div>
          <div class="bar"><span style="width:${width}%; background:${item.color};"></span></div>
        </div>`;
      }).join("");
    }

        function renderCards(payload) {
      const latest = payload.latest;
      const queue = payload.queue || { queue_depth: 0, active_holders: 0, capacity: 0, oldest_waiter_seconds: 0, other_lock_domains: [] };
      const last30 = sinceWindow(payload.series, 30);
      const last120 = sinceWindow(payload.series, 120);
      const cards = [
        {
          title: "CPU Load",
          value: latest.cpu_pct == null ? "warming up" : fmtPct(latest.cpu_pct),
          detail: `30m avg ${avg(last30, "cpu_pct") == null ? "n/a" : fmtPct(avg(last30, "cpu_pct"))} · load ${latest.load1.toFixed(2)} / ${latest.load5.toFixed(2)} / ${latest.load15.toFixed(2)}`,
        },
        {
          title: "Worker Fabric",
          value: `${latest.active_worker_lanes || 0} / ${latest.total_worker_lanes || 0} lanes`,
          detail: `${latest.busy_worker_count || 0} busy workers · ${fmtPct(latest.worker_saturation_pct || 0)} saturation · ${payload.worker_state?.worker_names?.join(", ") || "no workers discovered"}`,
        },
        {
          title: "Queue",
          value: `${queue.active_holders}/${queue.capacity} holding`,
          detail: `${queue.queue_depth} queued · oldest wait ${queue.queue_depth ? fmtDuration(Math.max(1, Math.round((queue.oldest_waiter_seconds || 0) / 60))) : "none"} · ${queue.other_lock_domains.length} extra lock domains`,
        },
        {
          title: "RAM",
          value: `${fmtGib(latest.mem_used_gb)} / ${fmtGib(latest.mem_total_gb)}`,
          detail: `${fmtPct(latest.mem_used_pct)} used · ${fmtGib(latest.mem_available_gb)} available`,
        },
        {
          title: "Swap",
          value: `${fmtGib(latest.swap_used_gb)} / ${fmtGib(latest.swap_total_gb)}`,
          detail: `${fmtPct(latest.swap_used_pct)} used`,
        },
        {
          title: "Root Disk",
          value: `${fmtGib(latest.disk_used_gb)} / ${fmtGib(latest.disk_total_gb)}`,
          detail: `${fmtPct(latest.disk_used_pct)} used`,
        },
        {
          title: "Disk I/O",
          value: `r ${latest.disk_read_mib_s == null ? "n/a" : fmtMibRate(latest.disk_read_mib_s)} · w ${latest.disk_write_mib_s == null ? "n/a" : fmtMibRate(latest.disk_write_mib_s)}`,
          detail: `${latest.disk_busy_pct == null ? "warming up" : `${fmtPct(latest.disk_busy_pct)} busy`} · ${latest.disk_await_ms == null ? "await n/a" : `${latest.disk_await_ms.toFixed(1)} ms await`} · ${latest.disk_device || "root device"}`,
        },
        {
          title: "Thermals",
          value: latest.temp_c == null ? "n/a" : `${fmt1(latest.temp_c)}C`,
          detail: `${payload.per_core_temp_available ? "Per-core thermal sensors live" : "Package + zone telemetry only"}`,
        },
        {
          title: "Network",
          value: `rx ${latest.rx_mib_s == null ? "n/a" : fmtMibRate(latest.rx_mib_s)}`,
          detail: `tx ${latest.tx_mib_s == null ? "n/a" : fmtMibRate(latest.tx_mib_s)} · 2h avg rx ${avg(last120, "rx_mib_s") == null ? "n/a" : fmtMibRate(avg(last120, "rx_mib_s"))}`,
        },
      ];
      cardsEl.innerHTML = cards.map((card) => `<article class="card"><h2>${card.title}</h2><div class="value">${card.value}</div><div class="detail">${card.detail}</div></article>`).join("");
    }

    function renderInventory(payload) {
      const hw = payload.hardware;
      const items = [
        ["Host", hw.hostname || payload.host],
        ["Kernel", hw.kernel || "n/a"],
        ["Architecture", hw.architecture || "n/a"],
        ["CPU Vendor ID", hw.vendor_id || "n/a"],
        ["CPU Model", hw.cpu_model || "n/a"],
        ["CPU Layout", `${hw.cpu_count || "?"} threads · ${hw.cores_per_socket || "?"} cores/socket · ${hw.threads_per_core || "?"} threads/core · ${hw.socket_count || "?"} socket`],
        ["CPU Clocks", `${hw.cpu_min_mhz || "?"} MHz min · ${hw.cpu_max_mhz || "?"} MHz max`],
        ["Memory", `${hw.memory_total_gb || "?"} GiB RAM · ${hw.swap_total_gb || "?"} GiB swap`],
        ["System", `${hw.system_vendor || "n/a"} ${hw.product_version || ""}`.trim()],
        ["Product", hw.product_name || "n/a"],
        ["Board", `${hw.board_vendor || "n/a"} ${hw.board_name || ""}`.trim()],
        ["BIOS", `${hw.bios_vendor || "n/a"} ${hw.bios_version || ""}`.trim()],
        ["Disk", `${hw.disk_name || "n/a"} · ${hw.disk_model || "n/a"} · ${hw.disk_size || "?"}`],
        ["Disk Serial", hw.disk_serial || "n/a"],
        ["IP Addresses", hw.ip_addresses || payload.remote_host],
      ];
      inventoryGridEl.innerHTML = items.map(([k, v]) => `<div class="kv"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
      inventoryNoteEl.textContent = `Static inventory from ${payload.remote_host}`;
    }

    function renderRunnerRow(item, tone, meta, sub) {
      return `<div class="runner-row">
        <div class="runner-top">
          <div class="runner-label"><span class="runner-dot" style="background:${tone}"></span>${item.label}</div>
          <div class="runner-meta">${meta}</div>
        </div>
        <div class="runner-sub">${sub}</div>
      </div>`;
    }

    function currentHistoryWindowMs(payload) {
      const series = payload.series || [];
      const nowMs = Date.now();
      if (!series.length) return { startMs: nowMs - 2 * 3600000, endMs: nowMs };
      const latestSampleMs = new Date(series[series.length - 1].timestamp).getTime();
      const endMs = Math.max(nowMs, latestSampleMs);
      const startMs = historyWindowMinutes == null
        ? new Date(series[0].timestamp).getTime()
        : endMs - historyWindowMinutes * 60 * 1000;
      return { startMs, endMs, latestSampleMs };
    }

    function runnerIdentity(item) {
      return item.path || item.label || item.name || item.owner || "runner";
    }

    function pctWithin(ms, startMs, endMs) {
      if (!Number.isFinite(ms) || endMs <= startMs) return 0;
      return Math.max(0, Math.min(100, ((ms - startMs) / (endMs - startMs)) * 100));
    }

    function runnerLaneBlock({ leftPct, widthPct, color, title, meta, chip, tooltipHtml = "", markKind = "", classes = "" }) {
      const tooltipAttr = tooltipHtml ? ` data-tooltip-html="${escapeHtml(tooltipHtml)}"` : "";
      const className = markKind ? `runner-swimlane-mark ${markKind} ${classes}`.trim() : `runner-swimlane-block ${classes}`.trim();
      if (markKind) {
        const style = `left:calc(${leftPct.toFixed(2)}% - 6px);width:12px;background:${color};`;
        return `<div class="${className}" style="${style}" title="${escapeHtml(title)}"${tooltipAttr}></div>`;
      }
      const safeWidth = Math.max(16, widthPct);
      const style = `left:calc(${leftPct.toFixed(2)}% + 6px);width:calc(${safeWidth.toFixed(2)}% - 12px);background:${color};`;
      return `<div class="${className}" style="${style}"${tooltipAttr}>
        <div class="swimlane-head">${escapeHtml(title)}</div>
        <div class="swimlane-meta">${escapeHtml(meta)}</div>
        ${chip ? `<div class="swimlane-chip">${escapeHtml(chip)}</div>` : ""}
      </div>`;
    }

    function runGradient(baseColor, live = false) {
      const exitColor = live ? '#f0a43a' : '#db6f66';
      return `linear-gradient(90deg, #2f8a73 0%, #49b695 10%, ${baseColor} 22%, ${baseColor} 78%, ${exitColor} 100%)`;
    }

    function renderRunnerSwimlaneAxis(payload) {
      const { startMs, endMs, latestSampleMs } = currentHistoryWindowMs(payload);
      const tickCount = window.innerWidth <= 700 ? 4 : 6;
      const labels = [];
      for (let idx = 0; idx < tickCount; idx += 1) {
        const ratio = tickCount === 1 ? 1 : idx / (tickCount - 1);
        const x = ratio * 100;
        const labelMs = startMs + (endMs - startMs) * ratio;
        labels.push(`<div class="axis-label" style="left:${x.toFixed(2)}%;">${idx === tickCount - 1 ? 'now' : timeLabel(labelMs)}</div>`);
      }
      runnerSwimlaneAxisEl.innerHTML = `<div></div><div class="axis-track">${labels.join("")}</div>`;
      if (runnerSwimlaneNoteEl) {
        const lagSeconds = Math.max(0, Math.round((endMs - (latestSampleMs || endMs)) / 1000));
        runnerSwimlaneNoteEl.textContent = `Live worker board across ${fmtDuration(historyWindowMinutes)}. Lanes drift against wall clock${lagSeconds > 5 ? ` · collector lag ${lagSeconds}s` : ''}.`;
      }
      return { startMs, endMs };
    }

    function ensureSwimlaneRow(boardEl, laneKey) {
      let row = [...boardEl.querySelectorAll('.runner-swimlane-row')].find((node) => node.dataset.laneKey === laneKey);
      if (!row) {
        row = document.createElement('div');
        row.className = 'runner-swimlane-row';
        row.dataset.laneKey = laneKey;
        row.innerHTML = `<div class="runner-swimlane-label">
          <div class="runner-swimlane-name"></div>
          <div class="runner-swimlane-sub"></div>
          <div class="runner-swimlane-sub"></div>
        </div>
        <div class="runner-swimlane-track"><div class="swimlane-now"></div></div>`;
        boardEl.appendChild(row);
      }
      return row;
    }

    function pruneSwimlaneRows(boardEl, keepKeys) {
      [...boardEl.querySelectorAll('.runner-swimlane-row')].forEach((row) => {
        if (!keepKeys.has(row.dataset.laneKey)) row.remove();
      });
      const empty = boardEl.querySelector('.runner-swimlane-empty');
      if (empty) empty.remove();
    }

    function setSwimlaneLabel(row, title, meta, sub, tooltipHtml = '') {
      const label = row.querySelector('.runner-swimlane-label');
      const nameEl = row.querySelector('.runner-swimlane-name');
      const subEls = row.querySelectorAll('.runner-swimlane-sub');
      nameEl.textContent = title;
      subEls[0].textContent = meta;
      subEls[0].style.display = 'none';
      subEls[1].textContent = sub;
      subEls[1].style.display = 'none';
      if (tooltipHtml) {
        label.dataset.tooltipHtml = tooltipHtml;
      } else {
        delete label.dataset.tooltipHtml;
      }
    }

    function clearSwimlaneBlock(row) {
      const block = row.querySelector('.runner-swimlane-block');
      if (block) block.remove();
    }

    function upsertSwimlaneBlock(row, { leftPct, widthPct, color, title, meta, chip, tooltipHtml = '', classes = '' }) {
      const track = row.querySelector('.runner-swimlane-track');
      let block = track.querySelector('.runner-swimlane-block');
      const created = !block;
      if (!block) {
        block = document.createElement('div');
        block.innerHTML = '<div class="swimlane-head"></div><div class="swimlane-meta"></div><div class="swimlane-chip"></div>';
        const nowRail = track.querySelector('.swimlane-now');
        track.insertBefore(block, nowRail || null);
      }
      block.className = `runner-swimlane-block ${classes}`.trim();
      block.style.left = `calc(${leftPct.toFixed(2)}% + 6px)`;
      block.style.width = `calc(${Math.max(10, widthPct).toFixed(2)}% - 12px)`;
      block.style.background = color;
      block.querySelector('.swimlane-head').textContent = title;
      block.querySelector('.swimlane-meta').textContent = meta;
      const chipEl = block.querySelector('.swimlane-chip');
      if (chip) {
        chipEl.textContent = chip;
        chipEl.style.display = '';
      } else {
        chipEl.textContent = '';
        chipEl.style.display = 'none';
      }
      if (tooltipHtml) {
        block.dataset.tooltipHtml = tooltipHtml;
      } else {
        delete block.dataset.tooltipHtml;
      }
      if (!created) block.classList.add('swimlane-live');
      return block;
    }

    function renderActiveRunnerSwimlanes(active, windowState) {
      if (!active.length) {
        activeRunnerListEl.innerHTML = `<div class="runner-swimlane-empty">No active worker lanes detected inside the current board window.</div>`;
        if (activeRunnerNoteEl) activeRunnerNoteEl.textContent = "No live worker lanes right now.";
        return;
      }
      const keepKeys = new Set();
      active.forEach((item, idx) => {
        const laneKey = `active-${idx}`;
        keepKeys.add(laneKey);
        const row = ensureSwimlaneRow(activeRunnerListEl, laneKey);
        const endMs = windowState.endMs;
        const durationMs = Math.max(60000, Math.round((item.seen_minutes || 1) * 60000));
        const rawStartMs = item.since ? new Date(item.since).getTime() : endMs - durationMs;
        const startMs = Math.max(windowState.startMs, rawStartMs);
        const runtimeMs = Math.max(0, endMs - rawStartMs);
        const leftPct = pctWithin(startMs, windowState.startMs, windowState.endMs);
        const widthPct = Math.max(10, 100 - leftPct);
        const label = item.label || item.name || "runner";
        const title = shortText(label, 44);
        const summary = shortText(`${fmtClock(rawStartMs)} -> now · ${fmtSpan(runtimeMs)} runtime`, 56);
        const tooltipHtml = swimlaneTooltipData(title, item.path || item.name || "path n/a", [
          { color: runnerColor(label), name: 'State', value: 'Live' },
          { color: '#f0a43a', name: 'Started', value: fmtTime(new Date(rawStartMs).toISOString()) },
          { color: '#4a83b1', name: 'Runtime', value: fmtSpan(runtimeMs) },
          { color: '#6d5fc2', name: 'Driver', value: item.driver || 'driver n/a' },
          { color: '#b55c2f', name: 'Processes', value: `${item.pid_count || 0}` },
        ]);
        setSwimlaneLabel(row, title, summary, item.path || item.name || "path n/a", tooltipHtml);
        upsertSwimlaneBlock(row, {
          leftPct,
          widthPct,
          color: runnerColor(label),
          title: summary,
          meta: title,
          chip: 'LIVE',
          tooltipHtml,
          classes: 'event-live',
        });
      });
      pruneSwimlaneRows(activeRunnerListEl, keepKeys);
      if (activeRunnerNoteEl) activeRunnerNoteEl.textContent = `${active.length} live ${active.length === 1 ? 'lane' : 'lanes'} rendered as running blocks.`;
    }

    function renderRecentRunnerSwimlanes(workerActivity, workerState, windowState) {
      const laneRows = ((workerActivity && workerActivity.lanes) ? workerActivity.lanes : []).filter((lane) => !lane.live);
      const totalLanes = Math.max(workerState?.total_lanes || 0, laneRows.length || 0);
      if (!laneRows.length) {
        recentRunnerEventsEl.innerHTML = `<div class="runner-swimlane-empty">No completed worker lane history is visible in this window.</div>`;
        if (recentRunnerNoteEl) recentRunnerNoteEl.textContent = 'Completed and idle lane history is not available yet.';
        return;
      }

      const keepKeys = new Set();
      let liveCount = 0;
      let completedCount = 0;
      let idleCount = 0;
      laneRows.forEach((lane, idx) => {
        const laneKey = lane.label || `${lane.worker || 'worker'}/${lane.lane || `lane-${String(idx + 1).padStart(2, '0')}`}`;
        keepKeys.add(laneKey);
        const row = ensureSwimlaneRow(recentRunnerEventsEl, laneKey);
        const workerName = lane.worker || 'worker';
        const laneName = lane.lane || laneKey;
        const title = shortText(lane.label || laneName, 44);

        if (lane.status === 'idle') {
          setSwimlaneLabel(
            row,
            title,
            `${workerName} · idle`,
            'No lease in the retained history window.',
            swimlaneTooltipData(title, 'Idle lane', [
              { color: '#8d8d76', name: 'State', value: 'Idle' },
              { color: '#4a83b1', name: 'Lane', value: laneName },
            ])
          );
          clearSwimlaneBlock(row);
          idleCount += 1;
          return;
        }

        const startIso = lane.since || lane.started_at || '';
        const endIso = lane.live ? windowState.endMs : (lane.ended_at || lane.stop_at || windowState.endMs);
        const startMs = startIso ? new Date(startIso).getTime() : windowState.endMs;
        const endMs = endIso ? new Date(endIso).getTime() : windowState.endMs;
        const clippedStartMs = Math.max(startMs, windowState.startMs);
        const clippedEndMs = Math.max(clippedStartMs + 60000, Math.min(endMs, windowState.endMs));
        const leftPct = pctWithin(clippedStartMs, windowState.startMs, windowState.endMs);
        const rightPct = pctWithin(clippedEndMs, windowState.startMs, windowState.endMs);
        const widthPct = Math.max(10, rightPct - leftPct);
        const runtimeMs = Math.max(0, endMs - startMs);
        const summary = shortText(`${fmtClock(startMs)} -> ${lane.live ? 'now' : fmtClock(endMs)} · ${fmtSpan(runtimeMs)}`, 56);
        const sub = shortText(lane.path || lane.owner || laneName, 72);
        const color = lane.live ? runnerColor(lane.label || lane.worker) : '#7f6a57';
        const blockTooltip = swimlaneTooltipData(title, sub, [
          { color, name: 'State', value: lane.live ? 'Live' : 'Completed' },
          { color: '#2f8a73', name: 'Start', value: fmtTime(new Date(startMs).toISOString()) },
          { color: '#9a5b55', name: 'Stop', value: lane.live ? 'In progress' : fmtTime(new Date(endMs).toISOString()) },
          { color: '#4a83b1', name: 'Runtime', value: fmtSpan(runtimeMs) },
          { color: '#6d5fc2', name: 'Driver', value: lane.driver || 'driver n/a' },
        ]);
        setSwimlaneLabel(row, title, summary, sub, blockTooltip);
        upsertSwimlaneBlock(row, {
          leftPct,
          widthPct,
          color: runGradient(color, lane.live),
          title: summary,
          meta: title,
          chip: lane.live ? 'LIVE' : 'LEASE',
          tooltipHtml: blockTooltip,
          classes: lane.live ? 'event-live' : 'event-run',
        });
        if (lane.live) liveCount += 1;
        else completedCount += 1;
      });
      pruneSwimlaneRows(recentRunnerEventsEl, keepKeys);
      const spare = Math.max(0, totalLanes - laneRows.length);
      if (recentRunnerNoteEl) recentRunnerNoteEl.textContent = laneRows.length
        ? `${laneRows.length} worker lanes shown · ${completedCount} completed · ${idleCount} idle${spare ? ` · ${spare} live above` : ''}.`
        : 'Completed and idle lane history is not available yet.';
    }

    function renderRunnerActivity(payload) {
      const workerActivity = payload.worker_activity || { active: [], recent: [], lanes: [] };
      const workerState = payload.worker_state || { active_lanes: 0, total_lanes: 0, busy_worker_count: 0, worker_count: 0 };
      const active = workerActivity.active || [];
      const windowState = renderRunnerSwimlaneAxis(payload);
      renderActiveRunnerSwimlanes(active, windowState);
      renderRecentRunnerSwimlanes(workerActivity, workerState, windowState);
      bindSwimlaneTooltips(activeRunnerListEl);
      bindSwimlaneTooltips(recentRunnerEventsEl);

      const latest = payload.latest;
      const device = latest.disk_device || payload.hardware.disk_name || "disk";
      const activeLanes = latest.active_worker_lanes ?? workerState.active_lanes ?? active.length;
      const totalLanes = latest.total_worker_lanes ?? workerState.total_lanes ?? 0;
      diskIoNoteEl.textContent = `${device} · read ${latest.disk_read_mib_s == null ? "n/a" : fmtMibRate(latest.disk_read_mib_s)} · write ${latest.disk_write_mib_s == null ? "n/a" : fmtMibRate(latest.disk_write_mib_s)} · busy ${latest.disk_busy_pct == null ? "n/a" : fmtPct(latest.disk_busy_pct)} · ${activeLanes} active worker lane${activeLanes === 1 ? "" : "s"}${totalLanes ? ` across ${totalLanes} total` : ""}`;
    }

    function renderWorkers(payload) {
      const workerState = payload.worker_state || { workers: [], active_lane_rows: [], active_lanes: 0, total_lanes: 0, busy_worker_count: 0, worker_count: 0 };
      const workerPalette = ["#c17a28", "#2f8a73", "#6d5fc2", "#4a83b1", "#9a5b55", "#7e8b2d"];
      if (!workerState.workers.length) {
        workerBreakdownEl.innerHTML = `<div class="detail">No worker roots discovered on the remote host.</div>`;
      } else {
        const maxLanes = Math.max(1, ...workerState.workers.map((worker) => worker.lane_count || 0));
        workerBreakdownEl.innerHTML = workerState.workers.map((worker, idx) => {
          const width = Math.max(4, ((worker.active_lanes || 0) / maxLanes) * 100);
          const color = workerPalette[idx % workerPalette.length];
          return `<div class="bar-row">
            <div class="bar-meta">
              <div class="bar-label">${worker.name}</div>
              <div class="bar-value">${worker.active_lanes}/${worker.lane_count} busy</div>
            </div>
            <div class="bar-track"><span style="width:${width}%; background:${color};"></span></div>
          </div>`;
        }).join("");
      }

      if (!workerState.active_lane_rows.length) {
        workerLaneListEl.innerHTML = `<div class="detail">No active worker leases right now.</div>`;
      } else {
        workerLaneListEl.innerHTML = workerState.active_lane_rows.map((lane) => {
          const meta = `${lane.launcher || 'launcher n/a'} · ${fmtDuration(Math.max(1, Math.round((lane.age_seconds || 0) / 60)))} · ${lane.display || 'display n/a'}`;
          const sub = `${lane.owner || 'owner n/a'} · ${lane.run_tag || 'run_tag n/a'} · ${lane.container_name || 'container n/a'}`;
          return renderRunnerRow({ label: lane.label || `${lane.worker}/${lane.lane}` }, runnerColor(lane.label || lane.worker), meta, sub);
        }).join("");
      }

      workerNoteEl.textContent = `${workerState.active_lanes}/${workerState.total_lanes} lanes active across ${workerState.busy_worker_count}/${workerState.worker_count} workers.`;
    }

    function renderQueue(payload) {
      const queue = payload.queue || { holders: [], waiters: [], wait_reason_mix: [], queue_depth: 0, active_holders: 0, capacity: 0 };
      const events = (payload.queue_activity?.recent || []).slice().reverse();
      const reasonPalette = ["#c17a28", "#2f8a73", "#6d5fc2", "#4a83b1", "#9a5b55", "#7e8b2d"];

      if (!queue.holders.length) {
        queueHolderListEl.innerHTML = `<div class="detail">No active holders for the host admission queue.</div>`;
      } else {
        queueHolderListEl.innerHTML = queue.holders.map((item) => {
          const meta = `${fmtDuration(Math.max(1, Math.round((item.age_seconds || 0) / 60)))} hold · pid ${item.pid || "?"}`;
          const sub = `${item.reason || "reason n/a"} · ${item.host || "host n/a"} · ${item.ticket || "slot"}`;
          return renderRunnerRow({ label: item.owner || item.ticket || "holder" }, "#2f8a73", meta, sub);
        }).join("");
      }

      if (!queue.waiters.length) {
        queueWaiterListEl.innerHTML = `<div class="detail">No waiters queued for the host admission queue.</div>`;
      } else {
        queueWaiterListEl.innerHTML = queue.waiters.map((item) => {
          const meta = `#${item.position || 0} · ${fmtDuration(Math.max(1, Math.round((item.age_seconds || 0) / 60)))} wait`;
          const sub = `${item.reason || "reason n/a"} · ${item.host || "host n/a"} · pid ${item.pid || "?"}`;
          return renderRunnerRow({ label: item.owner || item.ticket || "waiter" }, "#c17a28", meta, sub);
        }).join("");
      }

      renderCountRows(queueReasonBreakdownEl, queue.wait_reason_mix || [], reasonPalette, "waiter");

      if (!events.length) {
        queueEventListEl.innerHTML = `<div class="detail">No queue state changes yet in the retained history.</div>`;
      } else {
        queueEventListEl.innerHTML = events.map((event) => {
          const tone = queueEventColor(event.kind);
          const meta = `${event.kind} · ${fmtTime(event.timestamp)}`;
          const sub = `${event.reason || "reason n/a"} · ${event.note || event.ticket || ""}`;
          return renderRunnerRow(event, tone, meta, sub);
        }).join("");
      }
    }

    function renderSensors(payload) {
      thermalNoteEl.textContent = payload.per_core_temp_available
        ? "Per-core thermal sensors are exposed on this host"
        : "This host does not expose true per-core temperatures; package and board zones are shown instead";
      sensorGridEl.innerHTML = payload.latest.thermal_sensors.map((sensor) => `<div class="sensor-chip">
        <div class="small-head">${sensor.label}</div>
        <div class="sensor-value" style="color:${colorForSensor(sensor)}">${fmt1(sensor.temp_c)}C</div>
        <div class="detail">${sensor.kind} · ${sensor.source}</div>
      </div>`).join("");
    }

    function renderProcesses(payload) {
      const rows = payload.top_processes || [];
      if (!rows.length) {
        processTableWrapEl.innerHTML = `<div class="detail">No process pressure data available.</div>`;
        return;
      }
      processTableWrapEl.innerHTML = `<table>
        <thead>
          <tr>
            <th>PID</th>
            <th>Name</th>
            <th>CPU</th>
            <th>RSS</th>
            <th>Swap</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `<tr>
            <td>${row.pid}</td>
            <td>${row.name}</td>
            <td>${fmtPct(row.cpu_pct)}</td>
            <td>${fmtMib(row.rss_mib)}</td>
            <td>${fmtMib(row.swap_mib)}</td>
          </tr>`).join("")}
        </tbody>
      </table>`;
    }

    function ceilTo(value, step) {
      if (!Number.isFinite(value) || value <= 0) return step;
      return Math.ceil(value / step) * step;
    }

    function renderCountRows(target, items, palette, noun) {
      if (!items.length) {
        target.innerHTML = `<div class="detail">No current queue grouping data.</div>`;
        return;
      }
      const max = Math.max(1, ...items.map((item) => item.count || 0));
      target.innerHTML = items.map((item, idx) => {
        const width = Math.max(4, ((item.count || 0) / max) * 100);
        const color = palette[idx % palette.length];
        return `<div class="bar-row">
          <div class="bar-meta">
            <div class="bar-label">${item.label}</div>
            <div class="bar-value">${item.count} ${noun}${item.count === 1 ? "" : "s"}</div>
          </div>
          <div class="bar-track"><span style="width:${width}%; background:${color};"></span></div>
        </div>`;
      }).join("");
    }

    function renderBarRows(target, items, palette) {
      if (!items.length) {
        target.innerHTML = `<div class="detail">No current storage data.</div>`;
        return;
      }
      const max = Math.max(1, ...items.map((item) => item.size_gb || 0));
      target.innerHTML = items.map((item, idx) => {
        const width = Math.max(4, ((item.size_gb || 0) / max) * 100);
        const color = item.color || palette[idx % palette.length];
        return `<div class="bar-row">
          <div class="bar-meta">
            <div class="bar-label">${item.label}</div>
            <div class="bar-value">${fmtGib(item.size_gb || 0)}</div>
          </div>
          <div class="bar-track"><span style="width:${width}%; background:${color};"></span></div>
          ${item.path ? `<div class="bar-path">${item.path}</div>` : ""}
        </div>`;
      }).join("");
    }

    function renderStorage(payload) {
      const storage = payload.storage || { directories: [], namespaces: [] };
      const dirPalette = ["var(--disk)", "#bb6c2c", "#4c7f70", "#6f64b1", "#a76a55", "#66823d", "#3978b5", "#8f5674"];
      const namespacePalette = ["#a05a2c", "#4b7f6e", "#6d5fc2", "#c17a28", "#8c556f", "#4d83b6"];
      const namespaces = (storage.namespaces || [])
        .map((item) => ({ ...item, label: item.id === "runner_namespaces" ? "Worker Namespaces" : (item.label || item.name) }))
        .filter((item) => (item.size_gb || 0) > 0.1)
        .sort((a, b) => b.size_gb - a.size_gb);
      const namespaceTotal = namespaces.reduce((sum, item) => sum + (item.size_gb || 0), 0);
      const directories = (storage.directories || [])
        .map((item) => ({
          ...item,
          size_gb: item.id === "runner_namespaces" && (item.size_gb || 0) <= 0.1 ? namespaceTotal : item.size_gb,
        }))
        .filter((item) => (item.size_gb || 0) > 0.1)
        .sort((a, b) => b.size_gb - a.size_gb);
      renderBarRows(storageBreakdownEl, directories.slice(0, 7), dirPalette);
      renderBarRows(namespaceBreakdownEl, namespaces.slice(0, 6), namespacePalette);
      const lastEvent = (payload.disk_events || []).length ? payload.disk_events[payload.disk_events.length - 1] : null;
      const activeLanes = payload.latest.active_worker_lanes || 0;
      const totalLanes = payload.latest.total_worker_lanes || 0;
      storageNoteEl.textContent = `Root used ${fmtGib(payload.latest.disk_used_gb)} of ${fmtGib(payload.latest.disk_total_gb)} · ${lastEvent ? lastEvent.label : "no major disk cliffs in current history"} · ${activeLanes}/${totalLanes} worker lanes active`;
    }

    function storageReady(payload) {
      const storage = payload.storage || { directories: [], namespaces: [] };
      return (storage.directories || []).some((item) => (item.size_gb || 0) > 0.1)
        || (storage.namespaces || []).some((item) => (item.size_gb || 0) > 0.1);
    }

    function buildRunnerMarkers(payload, limit = 10) {
      const events = payload.worker_activity?.recent || [];
      return events
        .slice(-limit)
        .map((event) => ({
          x: new Date(event.timestamp).getTime(),
          kind: event.kind === "stop" ? "runner-stop" : "runner-start",
          color: runnerEventColor(event.kind),
          label: `${event.kind === "stop" ? "Stop" : "Start"} ${shortText(event.label, 22)}`,
        }));
    }

    function buildQueueMarkers(payload, limit = 12) {
      return (payload.queue_activity?.recent || [])
        .slice(-limit)
        .map((event) => ({
          x: new Date(event.timestamp).getTime(),
          kind: event.kind,
          color: queueEventColor(event.kind),
          label: `${event.kind[0].toUpperCase()}${event.kind.slice(1)} ${shortText(event.label, 18)}`,
        }));
    }

    function timeLabel(ms) {
      return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }

    function fmtDuration(minutes) {
      if (minutes == null) return "all retained history";
      if (minutes < 60) return `${minutes}m`;
      if (minutes % 60 === 0) return `${minutes / 60}h`;
      return `${(minutes / 60).toFixed(1)}h`;
    }

    function bucketHeatmapSamples(samples, cores, maxColumns) {
      if (samples.length <= maxColumns) return samples;
      const bucketSize = Math.ceil(samples.length / maxColumns);
      const buckets = [];
      for (let idx = 0; idx < samples.length; idx += bucketSize) {
        const group = samples.slice(idx, idx + bucketSize);
        const per_core_pct = {};
        cores.forEach((core) => {
          const values = group.map((sample) => sample.per_core_pct[core]).filter((value) => value !== null && value !== undefined);
          per_core_pct[core] = values.length
            ? Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 10) / 10
            : null;
        });
        buckets.push({
          timestamp: group[group.length - 1].timestamp,
          per_core_pct,
        });
      }
      return buckets;
    }

    function chartSeries(payload) {
      return historyWindowMinutes == null ? payload.series : sinceWindow(payload.series, historyWindowMinutes);
    }

    function renderHistoryControls(payload) {
      const availableMinutes = Math.max(
        0,
        Math.round((new Date(payload.updated_at).getTime() - new Date(payload.history_started_at).getTime()) / 60000)
      );
      historyRangeEl.innerHTML = historyWindows.map((windowDef) => {
        const active = windowDef.minutes === historyWindowMinutes;
        const disabled = windowDef.minutes !== null && availableMinutes < Math.max(windowDef.minutes / 4, 15);
        return `<button class="seg-btn${active ? " active" : ""}" data-minutes="${windowDef.minutes == null ? "all" : windowDef.minutes}" ${disabled ? "disabled" : ""}>${windowDef.label}</button>`;
      }).join("");
      const retainedSamples = payload.retained_sample_count || payload.sample_count || payload.series.length;
      const totalSamples = payload.total_sample_count || retainedSamples;
      const retention = totalSamples > retainedSamples
        ? ` · API retained ${retainedSamples}/${totalSamples} samples (${payload.series_retention_hours || Math.round(availableMinutes / 60)}h)`
        : ` · ${retainedSamples} samples`;
      historyNoteEl.textContent = (historyWindowMinutes == null
        ? `Showing all ${availableMinutes}m of retained chart history`
        : `Showing ${fmtDuration(historyWindowMinutes)} of ${availableMinutes}m retained chart history`) + retention;
      historyRangeEl.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
          const raw = button.dataset.minutes;
          historyWindowMinutes = raw === "all" ? null : Number(raw);
          if (lastPayload) render(lastPayload);
        });
      });
    }

    function measureChart(svg, defaults = {}) {
      const containerWidth = svg.clientWidth || svg.parentElement?.clientWidth || defaults.width || 760;
      const narrow = window.innerWidth <= 700 || containerWidth < 540;
      const chartWidth = narrow ? Math.min(defaults.width || 760, 760) : (defaults.width || 760);
      const chartHeight = narrow ? Math.max(defaults.height || 360, 420) : (defaults.height || 320);
      return {
        narrow,
        width: chartWidth,
        height: chartHeight,
        left: narrow ? 50 : 58,
        right: narrow ? 12 : 20,
        bottom: narrow ? 48 : 40,
        tickCount: narrow ? 4 : 6,
        fontSize: narrow ? 10 : 11,
      };
    }

    function buildLegend(lines, width, left, right, opts = {}) {
      const dotSize = opts.dotSize || 12;
      const fontSize = opts.fontSize || 11;
      const rowHeight = Math.max(opts.rowHeight || 0, 22);
      const labelFactor = Math.max(opts.labelFactor || 0, 7.2);
      const gap = Math.max(opts.gap || 0, 16);
      const startY = opts.startY || 8;
      const maxX = width - right;
      let x = left;
      let row = 0;
      let markup = "";

      lines.forEach((line) => {
        const itemWidth = dotSize + 14 + Math.max(36, line.name.length * labelFactor) + gap;
        if (x + itemWidth > maxX && x > left) {
          row += 1;
          x = left;
        }
        const y = startY + row * rowHeight;
        markup += `<rect x="${x}" y="${y}" width="${dotSize}" height="${dotSize}" rx="${dotSize / 2}" fill="${line.color}" />`;
        markup += `<text x="${x + dotSize + 6}" y="${y + dotSize / 2 + 1}" font-size="${fontSize}" fill="#4e5a66" dominant-baseline="middle">${line.name}</text>`;
        x += itemWidth;
      });

      return {
        markup,
        height: (row + 1) * rowHeight + 4,
      };
    }

    function drawLineChart(targetId, lines, opts = {}) {
      const svg = document.getElementById(targetId);
      const metrics = measureChart(svg, { width: opts.width || 760, height: opts.height || 320 });
      const width = metrics.width;
      const left = metrics.left;
      const right = metrics.right;
      const bottom = metrics.bottom;
      const plotWidth = width - left - right;
      const gapMs = opts.gapMs || 120000;

      const validLines = lines.map((line) => ({
        ...line,
        points: line.points.filter((point) => point.y !== null && point.y !== undefined),
      })).filter((line) => line.points.length);
      if (!validLines.length) {
        svg.innerHTML = "";
        hideChartTooltip();
        return;
      }

      const allPoints = validLines.flatMap((line) => line.points);
      const minX = Math.min(...allPoints.map((point) => point.x));
      const maxX = Math.max(...allPoints.map((point) => point.x));
      const spanX = Math.max(maxX - minX, 1);
      const markers = (opts.markers || []).filter((marker) => marker.x >= minX && marker.x <= maxX);
      const legend = buildLegend(validLines, width, left, right, {
        fontSize: metrics.fontSize,
        rowHeight: metrics.narrow ? 18 : 20,
        gap: metrics.narrow ? 10 : 14,
        labelFactor: metrics.narrow ? 6.1 : 6.6,
      });
      const top = 12 + legend.height;
      const height = metrics.height;
      const plotHeight = height - top - bottom;

      let minY = opts.yMin ?? Math.min(...allPoints.map((point) => point.y));
      let maxY = opts.yMax ?? Math.max(...allPoints.map((point) => point.y));
      if (opts.padMin != null) minY -= opts.padMin;
      if (opts.padMax != null) maxY += opts.padMax;
      if (maxY <= minY) maxY = minY + 1;

      const xFor = (x) => left + ((x - minX) / spanX) * plotWidth;
      const yFor = (y) => top + ((maxY - y) / (maxY - minY)) * plotHeight;

      function lineSegments(points) {
        if (!points.length) return [];
        const segments = [[points[0]]];
        for (let idx = 1; idx < points.length; idx += 1) {
          if (points[idx].x - points[idx - 1].x > gapMs) {
            segments.push([points[idx]]);
          } else {
            segments[segments.length - 1].push(points[idx]);
          }
        }
        return segments;
      }

      let markup = "";
      markup += legend.markup;
      const axisSteps = Math.max(2, metrics.tickCount - 1);

      for (let idx = 0; idx <= axisSteps; idx += 1) {
        const yValue = minY + ((maxY - minY) * idx) / axisSteps;
        const y = yFor(yValue);
        markup += `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="rgba(61,68,80,0.12)" stroke-width="1" />`;
        markup += `<text x="${left - 10}" y="${y + 4}" text-anchor="end" font-size="${metrics.fontSize}" fill="#63717e">${opts.yLabel ? opts.yLabel(yValue) : yValue.toFixed(1)}</text>`;
      }

      for (let idx = 0; idx <= axisSteps; idx += 1) {
        const xValue = minX + (spanX * idx) / axisSteps;
        const x = xFor(xValue);
        markup += `<line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="rgba(61,68,80,0.08)" stroke-width="1" />`;
        markup += `<text x="${x}" y="${height - 14}" text-anchor="middle" font-size="${metrics.fontSize}" fill="#63717e">${timeLabel(xValue)}</text>`;
      }

      markers.forEach((marker, idx) => {
        const x = xFor(marker.x);
        const color = marker.color || (marker.kind === "cleanup" ? "#2f8a73" : "#c97031");
        const anchor = x < left + 70 ? "start" : (x > width - right - 70 ? "end" : "middle");
        const labelX = anchor === "start" ? x + 4 : (anchor === "end" ? x - 4 : x);
        const labelY = top + 16 + (idx % 3) * 16;
        markup += `<line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="${color}" stroke-width="1.4" stroke-dasharray="4 6" opacity="0.7" />`;
        markup += `<text x="${labelX}" y="${labelY}" text-anchor="${anchor}" font-size="${metrics.fontSize}" fill="${color}">${marker.label}</text>`;
      });

      validLines.forEach((line) => {
        lineSegments(line.points).forEach((segment) => {
          if (segment.length === 1) {
            markup += `<circle cx="${xFor(segment[0].x)}" cy="${yFor(segment[0].y)}" r="2.5" fill="${line.color}" />`;
            return;
          }
          const points = segment.map((point) => `${xFor(point.x).toFixed(1)},${yFor(point.y).toFixed(1)}`).join(" ");
          markup += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="${line.width || 2.4}" stroke-linecap="round" stroke-linejoin="round" opacity="${line.opacity || 1}" />`;
        });
      });

      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = markup;
      bindLineTooltip(svg, {
        title: chartTitleForSvg(svg),
        lines: validLines,
        width,
        height,
        left,
        right,
        top,
        bottom,
        plotWidth,
        minX,
        spanX,
      });
    }

    function drawCoreHeatmap(payload) {
      const svg = document.getElementById("core-heatmap");
      const cores = payload.core_names || [];
      const selected = chartSeries(payload);
      if (!selected.length || !cores.length) {
        svg.innerHTML = "";
        return;
      }

      const narrow = window.innerWidth <= 700 || (svg.clientWidth || 0) < 560;
      const width = narrow ? 760 : 1200;
      const height = narrow ? 440 : 360;
      const left = narrow ? 72 : 90;
      const right = narrow ? 14 : 22;
      const top = 28;
      const bottom = narrow ? 52 : 40;
      const plotWidth = width - left - right;
      const plotHeight = height - top - bottom;
      const fontSize = narrow ? 10 : 11;
      const tickCount = narrow ? 4 : 6;
      const columnTarget = narrow ? 84 : 180;
      const samples = bucketHeatmapSamples(selected, cores, columnTarget);
      const cellWidth = plotWidth / samples.length;
      const cellHeight = plotHeight / cores.length;

      function heatColor(value) {
        const v = Math.max(0, Math.min(100, value ?? 0));
        const hue = 195 - (v / 100) * 170;
        const sat = 70;
        const light = 90 - (v / 100) * 42;
        return `hsl(${hue} ${sat}% ${light}%)`;
      }

      let markup = "";
      cores.forEach((core, rowIndex) => {
        const y = top + rowIndex * cellHeight;
        markup += `<text x="${left - 12}" y="${y + cellHeight * 0.62}" text-anchor="end" font-size="${fontSize}" fill="#5f6875">${core}</text>`;
        samples.forEach((sample, columnIndex) => {
          const value = sample.per_core_pct[core];
          const x = left + columnIndex * cellWidth;
          markup += `<rect x="${x}" y="${y}" width="${Math.max(1, cellWidth - 1)}" height="${Math.max(1, cellHeight - 1)}" fill="${heatColor(value)}" />`;
        });
      });

      for (let idx = 0; idx < tickCount; idx += 1) {
        const column = Math.floor((samples.length - 1) * idx / Math.max(1, tickCount - 1));
        const x = left + column * cellWidth + cellWidth / 2;
        markup += `<line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="rgba(61,68,80,0.12)" stroke-width="1" />`;
        markup += `<text x="${x}" y="${height - 14}" text-anchor="middle" font-size="${fontSize}" fill="#63717e">${timeLabel(new Date(samples[column].timestamp).getTime())}</text>`;
      }

      const legendX = left;
      markup += `<text x="${legendX}" y="16" font-size="${fontSize}" fill="#4e5a66">cool</text>`;
      [0, 1, 2, 3, 4].forEach((step) => {
        const pct = step * 25;
        markup += `<rect x="${legendX + 34 + step * 28}" y="6" width="24" height="12" rx="6" fill="${heatColor(pct)}" />`;
      });
      markup += `<text x="${legendX + 190}" y="16" font-size="${fontSize}" fill="#4e5a66">hot</text>`;

      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = markup;
      bindHeatmapTooltip(svg, {
        title: chartTitleForSvg(svg, "CPU Fabric"),
        width,
        height,
        left,
        right,
        top,
        bottom,
        cellWidth,
        cellHeight,
        samples,
        cores,
        colorForValue: heatColor,
      });
      const retainedHours = (
        (new Date(payload.updated_at).getTime() - new Date(payload.history_started_at).getTime()) / 3600000
      );
      heatmapNoteEl.textContent = `Per-core CPU utilization over ${fmtDuration(historyWindowMinutes)} · ${samples.length} buckets from ${selected.length} samples · ${retainedHours.toFixed(1)}h retained`;
    }

    function drawThermalChart(payload) {
      const samples = chartSeries(payload);
      const labels = [];
      samples.forEach((sample) => {
        sample.thermal_sensors.forEach((sensor) => {
          if (!labels.includes(sensor.label)) labels.push(sensor.label);
        });
      });
      const palette = ["var(--temp)", "var(--zone)", "#9d8f45", "#7f5cb6", "#2d7f73", "#2f6cca", "#b85d96", "#6d7f2d"];
      const lines = labels.map((label, idx) => ({
        name: label,
        color: palette[idx % palette.length],
        tooltip: (point) => point.y == null ? "n/a" : `${fmt1(point.y)}C`,
        points: samples.map((sample) => {
          const sensor = sample.thermal_sensors.find((entry) => entry.label === label);
          return { x: new Date(sample.timestamp).getTime(), y: sensor ? sensor.temp_c : null };
        }),
      }));
      const values = lines.flatMap((line) => line.points.map((point) => point.y).filter((value) => value !== null));
      drawLineChart("thermal-chart", lines, {
        width: 1200,
        height: 360,
        yMin: values.length ? Math.floor((Math.min(...values) - 5) / 5) * 5 : 30,
        yMax: values.length ? Math.ceil((Math.max(...values) + 5) / 5) * 5 : 95,
        yLabel: (value) => `${Math.round(value)}C`,
      });
    }

    function drawPressureChart(payload) {
      const svg = document.getElementById("pressure-chart");
      const samples = chartSeries(payload);
      if (!samples.length) {
        svg.innerHTML = "";
        return;
      }

      const hottestCorePoints = samples.map((sample) => {
        const values = Object.values(sample.per_core_pct || {}).filter((value) => value !== null && value !== undefined);
        return {
          x: new Date(sample.timestamp).getTime(),
          y: values.length ? Math.max(...values) : null,
        };
      });

      const leftLines = [
        {
          name: "Total CPU %",
          color: "var(--cpu)",
          tooltip: (point) => point.y == null ? "n/a" : fmtPct(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.cpu_pct })),
        },
        {
          name: "Hottest core %",
          color: "var(--load)",
          tooltip: (point) => point.y == null ? "n/a" : fmtPct(point.y),
          points: hottestCorePoints,
        },
        {
          name: "RAM %",
          color: "var(--mem)",
          tooltip: (point) => point.y == null ? "n/a" : fmtPct(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.mem_used_pct })),
        },
        {
          name: "Swap %",
          color: "var(--swap)",
          tooltip: (point) => point.y == null ? "n/a" : fmtPct(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.swap_used_pct })),
        },
        {
          name: "Disk %",
          color: "var(--disk)",
          tooltip: (point) => point.y == null ? "n/a" : fmtPct(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.disk_used_pct })),
        },
      ];
      const rightLines = [
        {
          name: "Package temp C",
          color: "var(--temp)",
          dash: "9 6",
          tooltip: (point) => point.y == null ? "n/a" : `${fmt1(point.y)}C`,
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.temp_c })),
        },
      ];

      const metrics = measureChart(svg, { width: 1200, height: 360 });
      const width = metrics.width;
      const height = metrics.height;
      const left = metrics.left;
      const right = metrics.narrow ? 62 : 76;
      const bottom = metrics.bottom;
      const allLines = [...leftLines, ...rightLines];
      const legend = buildLegend(allLines, width, left, right, {
        fontSize: metrics.fontSize,
        rowHeight: metrics.narrow ? 18 : 20,
        gap: metrics.narrow ? 10 : 14,
        labelFactor: metrics.narrow ? 6.1 : 6.8,
      });
      const top = 12 + legend.height;
      const plotWidth = width - left - right;
      const plotHeight = height - top - bottom;
      const gapMs = 120000;
      const allPoints = allLines.flatMap((line) => line.points.filter((point) => point.y !== null && point.y !== undefined));
      if (!allPoints.length) {
        svg.innerHTML = "";
        return;
      }
      const minX = Math.min(...allPoints.map((point) => point.x));
      const maxX = Math.max(...allPoints.map((point) => point.x));
      const spanX = Math.max(maxX - minX, 1);
      const leftAxisMax = 100;
      const rightAxisMax = Math.max(90, ceilTo(Math.max(...samples.map((sample) => sample.temp_c || 0), 80), 5));
      const axisSteps = Math.max(2, metrics.tickCount - 1);

      const xFor = (x) => left + ((x - minX) / spanX) * plotWidth;
      const leftYFor = (y) => top + ((leftAxisMax - y) / leftAxisMax) * plotHeight;
      const rightYFor = (y) => top + ((rightAxisMax - y) / rightAxisMax) * plotHeight;

      function lineSegments(points) {
        const filtered = points.filter((point) => point.y !== null && point.y !== undefined);
        if (!filtered.length) return [];
        const segments = [[filtered[0]]];
        for (let idx = 1; idx < filtered.length; idx += 1) {
          if (filtered[idx].x - filtered[idx - 1].x > gapMs) {
            segments.push([filtered[idx]]);
          } else {
            segments[segments.length - 1].push(filtered[idx]);
          }
        }
        return segments;
      }

      let markup = "";
      markup += legend.markup;

      for (let idx = 0; idx <= axisSteps; idx += 1) {
        const leftValue = (leftAxisMax * idx) / axisSteps;
        const rightValue = (rightAxisMax * idx) / axisSteps;
        const y = leftYFor(leftValue);
        markup += `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="rgba(61,68,80,0.12)" stroke-width="1" />`;
        markup += `<text x="${left - 10}" y="${y + 4}" text-anchor="end" font-size="${metrics.fontSize}" fill="#63717e">${Math.round(leftValue)}%</text>`;
        markup += `<text x="${width - right + 10}" y="${y + 4}" text-anchor="start" font-size="${metrics.fontSize}" fill="#63717e">${Math.round(rightValue)}C</text>`;
      }

      for (let idx = 0; idx <= axisSteps; idx += 1) {
        const xValue = minX + (spanX * idx) / axisSteps;
        const x = xFor(xValue);
        markup += `<line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="rgba(61,68,80,0.08)" stroke-width="1" />`;
        markup += `<text x="${x}" y="${height - 14}" text-anchor="middle" font-size="${metrics.fontSize}" fill="#63717e">${timeLabel(xValue)}</text>`;
      }

      leftLines.forEach((line) => {
        lineSegments(line.points).forEach((segment) => {
          if (segment.length === 1) {
            markup += `<circle cx="${xFor(segment[0].x)}" cy="${leftYFor(segment[0].y)}" r="2.5" fill="${line.color}" />`;
            return;
          }
          const points = segment.map((point) => `${xFor(point.x).toFixed(1)},${leftYFor(point.y).toFixed(1)}`).join(" ");
          markup += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="2.5" stroke-dasharray="${line.dash || ""}" stroke-linecap="round" stroke-linejoin="round" opacity="${line.opacity || 1}" />`;
        });
      });

      rightLines.forEach((line) => {
        lineSegments(line.points).forEach((segment) => {
          if (segment.length === 1) {
            markup += `<circle cx="${xFor(segment[0].x)}" cy="${rightYFor(segment[0].y)}" r="2.5" fill="${line.color}" />`;
            return;
          }
          const points = segment.map((point) => `${xFor(point.x).toFixed(1)},${rightYFor(point.y).toFixed(1)}`).join(" ");
          markup += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="2.4" stroke-dasharray="${line.dash || ""}" stroke-linecap="round" stroke-linejoin="round" opacity="0.95" />`;
        });
      });

      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = markup;
      bindLineTooltip(svg, {
        title: chartTitleForSvg(svg),
        lines: [...leftLines, ...rightLines],
        width,
        height,
        left,
        right,
        top,
        bottom,
        plotWidth,
        minX,
        spanX,
      });
    }

    function drawOpsChart(payload) {
      const samples = chartSeries(payload);
      const netMax = Math.max(1, ...samples.flatMap((sample) => [sample.rx_mib_s ?? 0, sample.tx_mib_s ?? 0]));
      const loadCeiling = Math.max(100, ...samples.flatMap((sample) => [sample.load1_pct ?? 0, sample.load5_pct ?? 0]));
      const yMax = Math.ceil(loadCeiling / 25) * 25;
      const scale = netMax > 0 ? yMax / netMax : 1;
      drawLineChart("ops-chart", [
        {
          name: "Load1/Core %",
          color: "var(--load)",
          tooltip: (point) => point.y == null ? "n/a" : fmtPct(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.load1_pct })),
        },
        {
          name: "Load5/Core %",
          color: "#7e8b2d",
          tooltip: (point) => point.y == null ? "n/a" : fmtPct(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.load5_pct })),
        },
        {
          name: "RX scaled",
          color: "var(--rx)",
          opacity: 0.9,
          tooltip: (point) => point.raw_mib_s == null ? "n/a" : fmtMibRate(point.raw_mib_s),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.rx_mib_s == null ? null : sample.rx_mib_s * scale, raw_mib_s: sample.rx_mib_s })),
        },
        {
          name: "TX scaled",
          color: "var(--tx)",
          opacity: 0.9,
          tooltip: (point) => point.raw_mib_s == null ? "n/a" : fmtMibRate(point.raw_mib_s),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.tx_mib_s == null ? null : sample.tx_mib_s * scale, raw_mib_s: sample.tx_mib_s })),
        },
      ], {
        width: 1200,
        height: 360,
        yMin: 0,
        yMax,
        yLabel: (value) => `${Math.round(value)}%`,
      });
    }

    function drawDiskIoChart(payload) {
      const svg = document.getElementById("disk-io-chart");
      const samples = chartSeries(payload);
      const leftLines = [
        {
          name: "Read MiB/s",
          color: "#4a83b1",
          tooltip: (point) => point.y == null ? "n/a" : fmtMibRate(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.disk_read_mib_s })),
        },
        {
          name: "Write MiB/s",
          color: "#b55c2f",
          tooltip: (point) => point.y == null ? "n/a" : fmtMibRate(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.disk_write_mib_s })),
        },
      ].map((line) => ({
        ...line,
        points: line.points.filter((point) => point.y !== null && point.y !== undefined),
      })).filter((line) => line.points.length);
      const rightLines = [
        {
          name: "Busy %",
          color: "#2f8a73",
          dash: "8 6",
          tooltip: (point) => point.y == null ? "n/a" : fmtPct(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.disk_busy_pct })),
        },
      ].map((line) => ({
        ...line,
        points: line.points.filter((point) => point.y !== null && point.y !== undefined),
      })).filter((line) => line.points.length);
      if (!leftLines.length && !rightLines.length) {
        svg.innerHTML = "";
        return;
      }

      const metrics = measureChart(svg, { width: 1200, height: 360 });
      const width = metrics.width;
      const heightBase = metrics.height;
      const left = metrics.left;
      const right = metrics.narrow ? 52 : 64;
      const bottom = metrics.bottom;
      const allLines = [...leftLines, ...rightLines];
      const legend = buildLegend(allLines, width, left, right, {
        fontSize: metrics.fontSize,
        rowHeight: metrics.narrow ? 18 : 20,
        gap: metrics.narrow ? 10 : 14,
        labelFactor: metrics.narrow ? 6.1 : 6.6,
      });
      const top = 12 + legend.height;
      const height = heightBase;
      const plotWidth = width - left - right;
      const plotHeight = height - top - bottom;
      const gapMs = 120000;

      const allPoints = allLines.flatMap((line) => line.points);
      const minX = Math.min(...allPoints.map((point) => point.x));
      const maxX = Math.max(...allPoints.map((point) => point.x));
      const spanX = Math.max(maxX - minX, 1);
      const leftMaxValue = Math.max(0.5, ...leftLines.flatMap((line) => line.points.map((point) => point.y || 0)));
      const leftYMax = ceilTo(leftMaxValue * 1.15, leftMaxValue < 4 ? 0.5 : 2);
      const rightYMax = 100;
      const markers = buildRunnerMarkers(payload, 10).filter((marker) => marker.x >= minX && marker.x <= maxX);
      const axisSteps = Math.max(2, metrics.tickCount - 1);

      const xFor = (x) => left + ((x - minX) / spanX) * plotWidth;
      const leftYFor = (y) => top + ((leftYMax - y) / leftYMax) * plotHeight;
      const rightYFor = (y) => top + ((rightYMax - y) / rightYMax) * plotHeight;

      function lineSegments(points) {
        if (!points.length) return [];
        const segments = [[points[0]]];
        for (let idx = 1; idx < points.length; idx += 1) {
          if (points[idx].x - points[idx - 1].x > gapMs) {
            segments.push([points[idx]]);
          } else {
            segments[segments.length - 1].push(points[idx]);
          }
        }
        return segments;
      }

      let markup = "";
      markup += legend.markup;

      for (let idx = 0; idx <= axisSteps; idx += 1) {
        const leftValue = (leftYMax * idx) / axisSteps;
        const rightValue = (rightYMax * idx) / axisSteps;
        const y = leftYFor(leftValue);
        markup += `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="rgba(61,68,80,0.12)" stroke-width="1" />`;
        markup += `<text x="${left - 10}" y="${y + 4}" text-anchor="end" font-size="${metrics.fontSize}" fill="#63717e">${leftValue.toFixed(leftYMax < 4 ? 1 : 0)}</text>`;
        markup += `<text x="${width - right + 10}" y="${y + 4}" text-anchor="start" font-size="${metrics.fontSize}" fill="#63717e">${Math.round(rightValue)}%</text>`;
      }

      for (let idx = 0; idx <= axisSteps; idx += 1) {
        const xValue = minX + (spanX * idx) / axisSteps;
        const x = xFor(xValue);
        markup += `<line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="rgba(61,68,80,0.08)" stroke-width="1" />`;
        markup += `<text x="${x}" y="${height - 14}" text-anchor="middle" font-size="${metrics.fontSize}" fill="#63717e">${timeLabel(xValue)}</text>`;
      }

      markers.forEach((marker, idx) => {
        const x = xFor(marker.x);
        const anchor = x < left + 70 ? "start" : (x > width - right - 70 ? "end" : "middle");
        const labelX = anchor === "start" ? x + 4 : (anchor === "end" ? x - 4 : x);
        const labelY = top + 16 + (idx % 3) * 16;
        markup += `<line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="${marker.color}" stroke-width="1.4" stroke-dasharray="4 6" opacity="0.7" />`;
        markup += `<text x="${labelX}" y="${labelY}" text-anchor="${anchor}" font-size="${metrics.fontSize}" fill="${marker.color}">${marker.label}</text>`;
      });

      leftLines.forEach((line) => {
        lineSegments(line.points).forEach((segment) => {
          if (segment.length === 1) {
            markup += `<circle cx="${xFor(segment[0].x)}" cy="${leftYFor(segment[0].y)}" r="2.5" fill="${line.color}" />`;
            return;
          }
          const points = segment.map((point) => `${xFor(point.x).toFixed(1)},${leftYFor(point.y).toFixed(1)}`).join(" ");
          markup += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />`;
        });
      });

      rightLines.forEach((line) => {
        lineSegments(line.points).forEach((segment) => {
          if (segment.length === 1) {
            markup += `<circle cx="${xFor(segment[0].x)}" cy="${rightYFor(segment[0].y)}" r="2.5" fill="${line.color}" />`;
            return;
          }
          const points = segment.map((point) => `${xFor(point.x).toFixed(1)},${rightYFor(point.y).toFixed(1)}`).join(" ");
          markup += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="2.4" stroke-dasharray="${line.dash || ""}" stroke-linecap="round" stroke-linejoin="round" opacity="0.95" />`;
        });
      });

      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = markup;
      bindLineTooltip(svg, {
        title: chartTitleForSvg(svg),
        lines: [...leftLines, ...rightLines],
        width,
        height,
        left,
        right,
        top,
        bottom,
        plotWidth,
        minX,
        spanX,
      });
    }

    function drawWorkerChart(payload) {
      const samples = chartSeries(payload);
      drawLineChart("worker-chart", [
        {
          name: "Active lanes",
          color: "#c17a28",
          tooltip: (point) => point.y == null ? "n/a" : `${Math.round(point.y)} lanes`,
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.active_worker_lanes ?? 0 })),
        },
        {
          name: "Total lanes",
          color: "#6d5fc2",
          dash: "10 6",
          tooltip: (point) => point.y == null ? "n/a" : `${Math.round(point.y)} lanes`,
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.total_worker_lanes ?? 0 })),
        },
        {
          name: "Busy workers",
          color: "#2f8a73",
          tooltip: (point) => point.y == null ? "n/a" : `${Math.round(point.y)} workers`,
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.busy_worker_count ?? 0 })),
        },
        {
          name: "Queue depth",
          color: "#4a83b1",
          dash: "8 6",
          tooltip: (point) => point.y == null ? "n/a" : `${Math.round(point.y)} waiting`,
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.queue_depth ?? 0 })),
        },
      ], {
        width: 1200,
        height: 360,
        yMin: 0,
        yMax: Math.max(4, ...samples.map((sample) => Math.max(sample.total_worker_lanes ?? 0, sample.active_worker_lanes ?? 0, sample.busy_worker_count ?? 0, sample.queue_depth ?? 0))) + 1,
        yLabel: (value) => `${Math.round(value)}`,
      });
    }

    function drawQueueChart(payload) {
      const svg = document.getElementById("queue-chart");
      const samples = chartSeries(payload);
      if (!samples.length) {
        svg.innerHTML = "";
        queueNoteEl.textContent = "No queue history retained yet.";
        return;
      }

      const leftLines = [
        {
          name: "Queue depth",
          color: "#c17a28",
          tooltip: (point) => point.y == null ? "n/a" : `${Math.round(point.y)}`,
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.queue_depth ?? 0 })),
        },
        {
          name: "Active holders",
          color: "#2f8a73",
          tooltip: (point) => point.y == null ? "n/a" : `${Math.round(point.y)}`,
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.queue_active_holders ?? 0 })),
        },
        {
          name: "Capacity",
          color: "#6d5fc2",
          dash: "10 6",
          tooltip: (point) => point.y == null ? "n/a" : `${Math.round(point.y)}`,
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.queue_capacity ?? 0 })),
        },
      ];
      const rightLines = [
        {
          name: "Oldest wait min",
          color: "#4a83b1",
          dash: "8 6",
          tooltip: (point) => point.y == null ? "n/a" : fmtDuration(Math.max(0, Math.round(point.y))),
          points: samples.map((sample) => ({
            x: new Date(sample.timestamp).getTime(),
            y: sample.queue_oldest_waiter_minutes ?? 0,
          })),
        },
      ];

      const metrics = measureChart(svg, { width: 1200, height: 360 });
      const width = metrics.width;
      const heightBase = metrics.height;
      const left = metrics.left;
      const right = metrics.narrow ? 60 : 74;
      const bottom = metrics.bottom;
      const allLines = [...leftLines, ...rightLines];
      const legend = buildLegend(allLines, width, left, right, {
        fontSize: metrics.fontSize,
        rowHeight: metrics.narrow ? 18 : 20,
        gap: metrics.narrow ? 10 : 14,
        labelFactor: metrics.narrow ? 6.1 : 6.6,
      });
      const top = 12 + legend.height;
      const height = heightBase;
      const plotWidth = width - left - right;
      const plotHeight = height - top - bottom;
      const gapMs = 120000;
      const allPoints = allLines.flatMap((line) => line.points);
      const minX = Math.min(...allPoints.map((point) => point.x));
      const maxX = Math.max(...allPoints.map((point) => point.x));
      const spanX = Math.max(maxX - minX, 1);
      const leftYMax = Math.max(
        1,
        ...samples.map((sample) => Math.max(sample.queue_depth ?? 0, sample.queue_active_holders ?? 0, sample.queue_capacity ?? 0))
      );
      const leftAxisMax = ceilTo(leftYMax * 1.15, leftYMax <= 4 ? 1 : 2);
      const rightYMaxValue = Math.max(10, ...samples.map((sample) => sample.queue_oldest_waiter_minutes ?? 0));
      const rightAxisMax = ceilTo(rightYMaxValue * 1.15, rightYMaxValue <= 20 ? 5 : 10);
      const markers = buildQueueMarkers(payload, 12).filter((marker) => marker.x >= minX && marker.x <= maxX);
      const axisSteps = Math.max(2, metrics.tickCount - 1);

      const xFor = (x) => left + ((x - minX) / spanX) * plotWidth;
      const leftYFor = (y) => top + ((leftAxisMax - y) / leftAxisMax) * plotHeight;
      const rightYFor = (y) => top + ((rightAxisMax - y) / rightAxisMax) * plotHeight;

      function lineSegments(points) {
        if (!points.length) return [];
        const segments = [[points[0]]];
        for (let idx = 1; idx < points.length; idx += 1) {
          if (points[idx].x - points[idx - 1].x > gapMs) {
            segments.push([points[idx]]);
          } else {
            segments[segments.length - 1].push(points[idx]);
          }
        }
        return segments;
      }

      let markup = "";
      markup += legend.markup;

      for (let idx = 0; idx <= axisSteps; idx += 1) {
        const leftValue = (leftAxisMax * idx) / axisSteps;
        const rightValue = (rightAxisMax * idx) / axisSteps;
        const y = leftYFor(leftValue);
        markup += `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="rgba(61,68,80,0.12)" stroke-width="1" />`;
        markup += `<text x="${left - 10}" y="${y + 4}" text-anchor="end" font-size="${metrics.fontSize}" fill="#63717e">${Math.round(leftValue)}</text>`;
        markup += `<text x="${width - right + 10}" y="${y + 4}" text-anchor="start" font-size="${metrics.fontSize}" fill="#63717e">${Math.round(rightValue)}m</text>`;
      }

      for (let idx = 0; idx <= axisSteps; idx += 1) {
        const xValue = minX + (spanX * idx) / axisSteps;
        const x = xFor(xValue);
        markup += `<line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="rgba(61,68,80,0.08)" stroke-width="1" />`;
        markup += `<text x="${x}" y="${height - 14}" text-anchor="middle" font-size="${metrics.fontSize}" fill="#63717e">${timeLabel(xValue)}</text>`;
      }

      markers.forEach((marker, idx) => {
        const x = xFor(marker.x);
        const anchor = x < left + 80 ? "start" : (x > width - right - 80 ? "end" : "middle");
        const labelX = anchor === "start" ? x + 4 : (anchor === "end" ? x - 4 : x);
        const labelY = top + 16 + (idx % 4) * 16;
        markup += `<line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="${marker.color}" stroke-width="1.4" stroke-dasharray="4 6" opacity="0.7" />`;
        markup += `<text x="${labelX}" y="${labelY}" text-anchor="${anchor}" font-size="${metrics.fontSize}" fill="${marker.color}">${marker.label}</text>`;
      });

      leftLines.forEach((line) => {
        lineSegments(line.points).forEach((segment) => {
          if (segment.length === 1) {
            markup += `<circle cx="${xFor(segment[0].x)}" cy="${leftYFor(segment[0].y)}" r="2.5" fill="${line.color}" />`;
            return;
          }
          const points = segment.map((point) => `${xFor(point.x).toFixed(1)},${leftYFor(point.y).toFixed(1)}`).join(" ");
          markup += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="2.6" stroke-dasharray="${line.dash || ""}" stroke-linecap="round" stroke-linejoin="round" />`;
        });
      });

      rightLines.forEach((line) => {
        lineSegments(line.points).forEach((segment) => {
          if (segment.length === 1) {
            markup += `<circle cx="${xFor(segment[0].x)}" cy="${rightYFor(segment[0].y)}" r="2.5" fill="${line.color}" />`;
            return;
          }
          const points = segment.map((point) => `${xFor(point.x).toFixed(1)},${rightYFor(point.y).toFixed(1)}`).join(" ");
          markup += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="2.4" stroke-dasharray="${line.dash || ""}" stroke-linecap="round" stroke-linejoin="round" opacity="0.95" />`;
        });
      });

      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = markup;
      bindLineTooltip(svg, {
        title: chartTitleForSvg(svg),
        lines: [...leftLines, ...rightLines],
        width,
        height,
        left,
        right,
        top,
        bottom,
        plotWidth,
        minX,
        spanX,
      });

      const queue = payload.queue || { queue_depth: 0, active_holders: 0, capacity: 0, oldest_waiter_seconds: 0, stale_waiter_count: 0 };
      const oldestWait = queue.queue_depth
        ? fmtDuration(Math.max(1, Math.round((queue.oldest_waiter_seconds || 0) / 60)))
        : "none";
      const eventCount = (payload.queue_activity?.recent || []).length;
      queueNoteEl.textContent = `${queue.lock_name || "runner-host"} · ${queue.active_holders}/${queue.capacity} holding · ${queue.queue_depth} waiting · oldest wait ${oldestWait} · ${eventCount} recent queue event${eventCount === 1 ? "" : "s"}${queue.stale_waiter_count ? ` · ${queue.stale_waiter_count} stale waiter candidate${queue.stale_waiter_count === 1 ? "" : "s"}` : ""}`;
    }

    function drawStorageChart(payload) {
      const samples = chartSeries(payload);
      const markers = [
        ...(payload.disk_events || []).map((event) => ({
          ...event,
          x: new Date(event.timestamp).getTime(),
        })),
        ...buildRunnerMarkers(payload, 8),
      ].sort((a, b) => a.x - b.x).slice(-12);
      const diskTotal = Math.max(...samples.map((sample) => sample.disk_total_gb || 0), payload.latest.disk_total_gb || 0);
      drawLineChart("storage-chart", [
        {
          name: "Root used GiB",
          color: "var(--disk)",
          tooltip: (point) => point.y == null ? "n/a" : fmtGib(point.y),
          points: samples.map((sample) => ({ x: new Date(sample.timestamp).getTime(), y: sample.disk_used_gb })),
        },
      ], {
        width: 1200,
        height: 360,
        yMin: 0,
        yMax: ceilTo(Math.max(diskTotal, payload.latest.disk_used_gb), 16),
        yLabel: (value) => `${Math.round(value)} GiB`,
        markers,
      });
    }

    function drawProcessTrendChart(payload) {
      const svg = document.getElementById("process-trend-chart");
      const trend = payload.process_trends || { lines: [], metric: "swap_mib", window_minutes: 720 };
      if (!trend.lines || !trend.lines.length) {
        svg.innerHTML = "";
        processTrendNoteEl.textContent = "No historical process pressure trail is available yet.";
        return;
      }
      const cutoff = historyWindowMinutes == null
        ? null
        : new Date(payload.series[payload.series.length - 1].timestamp).getTime() - historyWindowMinutes * 60 * 1000;
      const palette = ["#b55c2f", "#4f7c71", "#655ac2", "#c48d32", "#4a83b1", "#8d5d75"];
      const lines = trend.lines.map((line, idx) => ({
        name: line.name,
        color: palette[idx % palette.length],
        tooltip: (point) => point.y == null ? "n/a" : fmtMib(point.y),
        points: line.points
          .map((point) => ({
            x: new Date(point.x).getTime(),
            y: point.y,
          }))
          .filter((point) => cutoff == null || point.x >= cutoff),
      })).filter((line) => line.points.length);
      if (!lines.length) {
        svg.innerHTML = "";
        processTrendNoteEl.textContent = historyWindowMinutes == null
          ? 'No process history is available yet across retained history.'
          : `No ${fmtDuration(historyWindowMinutes)} process history is available yet.`;
        return;
      }
      const maxValue = Math.max(
        1,
        ...lines.flatMap((line) => line.points.map((point) => point.y || 0))
      );
      drawLineChart("process-trend-chart", lines, {
        width: 1200,
        height: 360,
        yMin: 0,
        yMax: ceilTo(maxValue * 1.15, trend.metric === "swap_mib" ? 256 : 512),
        yLabel: (value) => `${Math.round(value)} MiB`,
      });
      processTrendNoteEl.textContent = historyWindowMinutes == null
        ? `${trend.metric === "swap_mib" ? "Swap" : "RSS"} trail for dominant processes across all retained history`
        : `${trend.metric === "swap_mib" ? "Swap" : "RSS"} trail for dominant processes over the last ${fmtDuration(historyWindowMinutes)}`;
    }

    function render(payload) {
      lastPayload = payload;
      renderHeadline(payload);
      renderAlerts(payload);
      renderPressure(payload);
      renderCards(payload);
      renderInventory(payload);
      renderWorkers(payload);
      renderQueue(payload);
      renderSensors(payload);
      renderProcesses(payload);
      renderStorage(payload);
      drawVisible("runner-swimlane-axis", () => renderRunnerActivity(payload));
      drawVisible("core-heatmap", () => drawCoreHeatmap(payload));
      drawVisible("thermal-chart", () => drawThermalChart(payload));
      drawVisible("pressure-chart", () => drawPressureChart(payload));
      drawVisible("ops-chart", () => drawOpsChart(payload));
      drawVisible("disk-io-chart", () => drawDiskIoChart(payload));
      drawVisible("worker-chart", () => drawWorkerChart(payload));
      drawVisible("queue-chart", () => drawQueueChart(payload));
      drawVisible("storage-chart", () => drawStorageChart(payload));
      drawVisible("process-trend-chart", () => drawProcessTrendChart(payload));
      renderHistoryControls(payload);
      if (!storageReady(payload)) {
        storageNoteEl.textContent += " · warming storage inventory";
        if (!storageWarmTimer) {
          storageWarmTimer = setTimeout(() => {
            storageWarmTimer = null;
            refresh();
          }, 4000);
        }
      } else if (storageWarmTimer) {
        clearTimeout(storageWarmTimer);
        storageWarmTimer = null;
      }
      pressureNoteEl.textContent = payload.last_error
        ? `Last collector error: ${payload.last_error}`
        : `Polling ${payload.remote_host} every ${payload.poll_interval_seconds}s`;
    }

    async function refresh() {
      try {
        const response = await fetch(`/api/data?ts=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        render(payload);
      } catch (error) {
        heroMetaEl.textContent = `Refresh failed: ${error.message}`;
      }
    }

    initDashboardTabs();
    refresh();
    setInterval(refresh, 30000);
    setInterval(() => {
      if (!lastPayload || document.hidden) return;
      if (chartIsVisible("runner-swimlane-axis")) renderRunnerActivity(lastPayload);
    }, 1000);
    window.addEventListener("resize", () => {
      if (!lastPayload) return;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => render(lastPayload), 120);
    });
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    store: HistoryStore
    hardware_cache: HardwareCache
    storage_cache: StorageCache
    payload_cache: PayloadCache

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.respond_html(HTML)
            return
        if parsed.path == "/api/data":
            try:
                payload = self.payload_cache.get(self.store, self.hardware_cache, self.storage_cache)
            except Exception as exc:  # pragma: no cover
                self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
                return
            self.respond_json(payload)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def respond_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.write_response_body(encoded)

    def respond_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.write_response_body(encoded)

    def write_response_body(self, encoded: bytes) -> None:
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> int:
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    store = HistoryStore(HISTORY_FILE)
    hardware_cache = HardwareCache()
    storage_cache = StorageCache()
    payload_cache = PayloadCache()

    if not store.snapshot()[0]:
        store.append(fetch_remote_sample())

    collector = threading.Thread(target=collector_loop, args=(store,), daemon=True)
    collector.start()
    storage_collector = threading.Thread(target=storage_loop, args=(storage_cache,), daemon=True)
    storage_collector.start()

    Handler.store = store
    Handler.hardware_cache = hardware_cache
    Handler.storage_cache = storage_cache
    Handler.payload_cache = payload_cache
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving http://{HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
