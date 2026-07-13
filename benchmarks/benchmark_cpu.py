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
from concurrent.futures import ProcessPoolExecutor
from typing import Callable


# ── single-thread workloads ───────────────────────────────────────────────────

def count_primes(limit: int) -> int:
    count = 0
    for n in range(2, limit):
        root = int(math.isqrt(n))
        for factor in range(2, root + 1):
            if n % factor == 0:
                break
        else:
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


# ── parallel worker functions (must be top-level for pickling) ────────────────

def _primes_chunk(args: tuple) -> int:
    start, end = args
    count = 0
    for n in range(max(2, start), end):
        root = int(math.isqrt(n))
        for factor in range(2, root + 1):
            if n % factor == 0:
                break
        else:
            count += 1
    return count


def _monte_carlo_chunk(args: tuple) -> int:
    iterations, seed = args
    rng = random.Random(seed)
    inside = 0
    for _ in range(iterations):
        x = rng.random()
        y = rng.random()
        if x * x + y * y <= 1.0:
            inside += 1
    return inside


def _sha256_chunk(args: tuple) -> str:
    block_size, rounds = args
    data = b"x" * block_size
    digest = b""
    for _ in range(rounds):
        digest = hashlib.sha256(data + digest).digest()
    return digest.hex()


# ── measurement helpers ───────────────────────────────────────────────────────

def measure_single(fn: Callable[[], object], repeats: int) -> tuple[object, list[float]]:
    durations = []
    result = None
    for _ in range(repeats):
        t = time.perf_counter()
        result = fn()
        durations.append(time.perf_counter() - t)
    return result, durations


def measure_parallel(pool: ProcessPoolExecutor, worker_fn: Callable, chunks: list, repeats: int) -> list[float]:
    durations = []
    for _ in range(repeats):
        t = time.perf_counter()
        list(pool.map(worker_fn, chunks))
        durations.append(time.perf_counter() - t)
    return durations


def build_chunks(task: str, num_workers: int, **kw) -> list:
    if task == "primes":
        limit = kw["limit"]
        size = limit // num_workers
        return [(i * size, (i + 1) * size if i < num_workers - 1 else limit) for i in range(num_workers)]
    elif task == "pi":
        iters = kw["iterations"]
        per = iters // num_workers
        return [(per + (1 if i < iters % num_workers else 0), i) for i in range(num_workers)]
    elif task == "sha256":
        rounds = kw["rounds"]
        per = rounds // num_workers
        block_size = kw["block_size"]
        return [(block_size, per + (1 if i < rounds % num_workers else 0)) for i in range(num_workers)]


def print_results(label: str, durations: list[float], result=None) -> float:
    avg = statistics.mean(durations)
    print(f"    {label}")
    if result is not None:
        print(f"      Result:   {result}")
    print(f"      Runs:     {', '.join(f'{d:.3f}s' for d in durations)}")
    print(f"      Fastest:  {min(durations):.3f}s   Average: {avg:.3f}s")
    return avg


def print_system_info(num_workers: int) -> None:
    print("System info")
    print(f"  Python:     {sys.version.split()[0]}")
    print(f"  Platform:   {platform.platform()}")
    print(f"  Processor:  {platform.processor() or 'unknown'}")
    print(f"  CPU count:  {os.cpu_count() or 'unknown'}   Workers used: {num_workers}")
    print()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CPU benchmark: single-thread vs multi-process (same total work).")
    parser.add_argument("--repeats",        type=int, default=3)
    parser.add_argument("--prime-limit",    type=int, default=50_000)
    parser.add_argument("--pi-iterations",  type=int, default=2_000_000)
    parser.add_argument("--hash-rounds",    type=int, default=300_000)
    parser.add_argument("--hash-block-size",type=int, default=4096)
    parser.add_argument("--workers",        type=int, default=None,
                        help="Parallel workers (default: CPU count).")
    args = parser.parse_args()

    num_workers = args.workers or (os.cpu_count() or 1)
    print_system_info(num_workers)

    benchmarks = [
        {
            "name":        "Prime count",
            "single_fn":   lambda: count_primes(args.prime_limit),
            "worker_fn":   _primes_chunk,
            "chunks":      build_chunks("primes", num_workers, limit=args.prime_limit),
        },
        {
            "name":        "Monte Carlo Pi",
            "single_fn":   lambda: monte_carlo_pi(args.pi_iterations),
            "worker_fn":   _monte_carlo_chunk,
            "chunks":      build_chunks("pi", num_workers, iterations=args.pi_iterations),
        },
        {
            "name":        "SHA-256 stress",
            "single_fn":   lambda: sha256_stress(args.hash_block_size, args.hash_rounds),
            "worker_fn":   _sha256_chunk,
            "chunks":      build_chunks("sha256", num_workers, rounds=args.hash_rounds, block_size=args.hash_block_size),
        },
    ]

    print(f"Benchmark results  (single-thread vs {num_workers}-process, same total work)\n")

    st_avgs, mt_avgs = [], []

    # Pre-warm process pool so spawn overhead doesn't pollute timings.
    with ProcessPoolExecutor(max_workers=num_workers) as pool:
        list(pool.map(_primes_chunk, [(0, 2)] * num_workers))  # warm-up

        for b in benchmarks:
            print(f"  {b['name']}")
            result, st_dur = measure_single(b["single_fn"], args.repeats)
            st_avg = print_results("Single-thread", st_dur, result)

            mt_dur = measure_parallel(pool, b["worker_fn"], b["chunks"], args.repeats)
            mt_avg = print_results(f"Multi-process ({num_workers}w)", mt_dur)

            speedup = st_avg / mt_avg if mt_avg > 0 else float("inf")
            print(f"      Speedup:  {speedup:.2f}x\n")

            st_avgs.append(st_avg)
            mt_avgs.append(mt_avg)

    overall_st = statistics.mean(st_avgs)
    overall_mt = statistics.mean(mt_avgs)
    print(f"Overall single-thread average:  {overall_st:.3f}s")
    print(f"Overall multi-process average:  {overall_mt:.3f}s")
    print(f"Overall speedup:                {overall_st / overall_mt:.2f}x")
    print("Lower times and higher speedup are better.")


if __name__ == "__main__":
    main()
