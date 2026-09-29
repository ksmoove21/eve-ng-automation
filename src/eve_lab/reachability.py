"""Bounded convergence tolerance for read-only reachability probes."""
import time


def retry_ping(probe, minimum_success_rate=100):
    """Return the best result and every attempt; never delay after success."""
    attempts = []
    for number in range(3):
        if number:
            time.sleep(10)
        observed = probe()
        attempts.append(observed)
        if observed["success_rate"] >= minimum_success_rate:
            break
    best = max(attempt["success_rate"] for attempt in attempts)
    return best >= minimum_success_rate, best, attempts
