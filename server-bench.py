#!/usr/bin/env python3
"""Linux system information and disk benchmark. Python 3.6+; fully offline.

Usage: python3 server-bench.py [options]
"""
import argparse
import os
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MIB = 1024 * 1024
COLOR = False


def clean(value):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value)).strip()


def paint(value, color="36"):
    value = clean(value)
    return "\033[" + color + "m" + value + "\033[0m" if COLOR else value


def row(label, value):
    print("{:<22}: {}".format(label, paint(value)), flush=True)


def line():
    print("-" * 79, flush=True)


def read(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def command(args, timeout=5):
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, universal_newlines=True)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def memory_pair(used, total):
    return "{:.0f} MiB / {:.0f} MiB".format(used / 1024, total / 1024)


def system_info(directory):
    cpu = {}
    for entry in read("/proc/cpuinfo").split("\n\n")[0].splitlines():
        if ":" in entry:
            key, val = entry.split(":", 1)
            cpu[key.strip()] = val.strip()
    osinfo = {}
    for entry in read("/etc/os-release").splitlines():
        if "=" in entry:
            key, val = entry.split("=", 1)
            osinfo[key] = val.strip('"')
    mem = {}
    for entry in read("/proc/meminfo").splitlines():
        key, val = entry.split(":", 1)
        mem[key] = int(val.strip().split()[0])
    row("CPU Model", cpu.get("model name", cpu.get("Processor", platform.machine())))
    try:
        available = len(os.sched_getaffinity(0))
    except AttributeError:
        available = os.cpu_count()
    row("CPU Cores", "{} available / {} online, {} MHz, {}".format(
        available, os.cpu_count(), cpu.get("cpu MHz", "N/A"), platform.machine()))
    row("CPU Cache", cpu.get("cache size", "N/A"))
    virt = command(["systemd-detect-virt"]) or "unknown / bare metal"
    row("OS", "{} ({})".format(osinfo.get("PRETTY_NAME", platform.system()), virt))
    row("Kernel", platform.release())
    usage = shutil.disk_usage(directory)
    row("Space (test filesystem)", "{:.1f} GiB / {:.1f} GiB".format(
        usage.used / MIB / 1024, usage.total / MIB / 1024))
    row("Disk Test Directory", str(directory))
    if mem:
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        row("Total RAM", memory_pair(max(0, total - avail), total))
        swap = mem.get("SwapTotal", 0)
        row("Total SWAP", memory_pair(swap - mem.get("SwapFree", 0), swap))
    uptime = read("/proc/uptime").split()
    if uptime:
        minutes = int(float(uptime[0])) // 60
        row("Uptime", "{} days {} hours {} min".format(minutes // 1440, minutes // 60 % 24, minutes % 60))
    row("Load Average", ", ".join(read("/proc/loadavg").split()[:3]) or "N/A")
    row("TCP CC", read("/proc/sys/net/ipv4/tcp_congestion_control") or "N/A")
    row("Memory Scope", "Kernel /proc view; container limits may differ")


def disk_test(directory, size_mib, rounds):
    size = size_mib * MIB
    if shutil.disk_usage(directory).free < size + 256 * MIB:
        row("Disk Test", "SKIPPED: need test size + 256 MiB free")
        return False
    speeds = []
    # The same random block is reused; deduplication can still inflate results.
    block = os.urandom(MIB)
    try:
        with tempfile.TemporaryDirectory(prefix="server-bench-", dir=str(directory)) as temp:
            target = Path(temp) / "write-test.bin"
            for _round in range(rounds):
                start = time.perf_counter()
                with open(str(target), "wb", buffering=0) as handle:
                    for _ in range(size_mib):
                        pending = memoryview(block)
                        while pending:
                            written = handle.write(pending)
                            if not written:
                                raise OSError("short write")
                            pending = pending[written:]
                    os.fsync(handle.fileno())
                elapsed = time.perf_counter() - start
                if elapsed <= 0:
                    raise OSError("timer resolution too low; increase --disk-mib")
                speed = size / elapsed / 1000000
                speeds.append(speed)
                row("I/O Speed ({:.2f} GiB)".format(size_mib / 1024), "{:.2f} MB/s".format(speed))
                target.unlink()
        row("Average I/O Speed", "{:.2f} MB/s".format(statistics.mean(speeds)))
        print("Sequential write + fsync; filesystem/cache/dedup can affect results.")
        return True
    except OSError as exc:
        row("Disk Test", "FAILED: " + str(exc))
        return False


def integer_between(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError("must be between {} and {}".format(low, high))
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--disk-dir", default=".", help="existing writable directory on the disk to test")
    parser.add_argument("--disk-mib", type=integer_between(1, 65536), default=1024, help="temporary disk file size in MiB")
    parser.add_argument("--rounds", type=integer_between(1, 10), default=3, help="disk write rounds")
    parser.add_argument("--skip-disk", action="store_true", help="skip disk writes")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("Run this script on the target Linux server, not on Windows.")
    directory = Path(args.disk_dir).expanduser().resolve()
    if not directory.is_dir():
        parser.error("--disk-dir must be an existing directory")
    global COLOR
    COLOR = sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ
    line()
    print(paint("Linux System & Disk Benchmark | " + time.strftime("%Y-%m-%d %H:%M:%S %Z"), "32"))
    system_info(directory)
    line()
    success = True
    if not args.skip_disk:
        success = disk_test(directory, args.disk_mib, args.rounds) and success
        line()
    return 0 if success else 1


if __name__ == "__main__":
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled; temporary disk file cleaned up.", file=sys.stderr)
        sys.exit(130)
