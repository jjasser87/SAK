#!/usr/bin/env python3

import argparse
import hashlib
import math
import os
import platform
import random
import statistics
import sys
import time
from typing import Callable


def count_primes(limit: int) -> int:
    count = 0
    for n in range(2, limit):
        is_prime = True
        root = int(math.isqrt(n))
        for factor in range(2, root + 1):
            if n % factor == 0:
                is_prime = False
                break
        if is_prime:
            count += 1
    return count


def monte_carlo_pi(iterations: int) -> float:
    rng = random.Random(42)
    inside = 0
    for _ in range(iterations):
        x = rng.random()
        y = rng.random()
        if x * x + y * y <= 1.0:
            inside += 1
    return 4.0 * inside / iterations


def sha256_stress(block_size: int, rounds: int) -> str:
    data = b"x" * block_size
    digest = b""
    for _ in range(rounds):
        digest = hashlib.sha256(data + digest).digest()
    return digest.hex()


def measure(task_name: str, fn: Callable[[], object], repeats: int) -> tuple[str, object, list[float]]:
    durations = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        durations.append(time.perf_counter() - start)
    return task_name, result, durations


def print_system_info() -> None:
    print("System info")
    print(f"  Python:     {sys.version.split()[0]}")
    print(f"  Platform:   {platform.platform()}")
    print(f"  Machine:    {platform.machine()}")
    print(f"  Processor:  {platform.processor() or 'unknown'}")
    print(f"  CPU count:  {os.cpu_count() or 'unknown'}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a simple CPU benchmark to compare Intel and Apple M-series systems."
    )
    parser.add_argument("--repeats", type=int, default=3, help="How many times to run each test.")
    parser.add_argument("--prime-limit", type=int, default=50_000, help="Upper bound for prime counting.")
    parser.add_argument(
        "--pi-iterations",
        type=int,
        default=2_000_000,
        help="Iterations for the Monte Carlo Pi estimate.",
    )
    parser.add_argument(
        "--hash-rounds",
        type=int,
        default=300_000,
        help="SHA-256 rounds to execute.",
    )
    parser.add_argument(
        "--hash-block-size",
        type=int,
        default=4096,
        help="Size in bytes of the buffer hashed in each round.",
    )
    args = parser.parse_args()

    benchmarks = [
        ("Prime count", lambda: count_primes(args.prime_limit)),
        ("Monte Carlo Pi", lambda: monte_carlo_pi(args.pi_iterations)),
        ("SHA-256 stress", lambda: sha256_stress(args.hash_block_size, args.hash_rounds)),
    ]

    print_system_info()
    print("Benchmark results")

    summary = []
    for task_name, fn in benchmarks:
        name, result, durations = measure(task_name, fn, args.repeats)
        avg = statistics.mean(durations)
        fastest = min(durations)
        summary.append((name, avg))
        print(f"  {name}")
        print(f"    Result:   {result}")
        print(f"    Runs:     {', '.join(f'{d:.3f}s' for d in durations)}")
        print(f"    Fastest:  {fastest:.3f}s")
        print(f"    Average:  {avg:.3f}s")

    overall = statistics.mean(avg for _, avg in summary)
    print()
    print(f"Overall average across tests: {overall:.3f}s")
    print("Lower times are better.")


if __name__ == "__main__":
    main()
