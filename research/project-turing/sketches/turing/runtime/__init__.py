"""Project Turing runtime layer.

Production-shaped glue that wires the library in `turing/` to real providers,
real workloads, real observation windows. Matches the library's Reactor
contract so tests and production share `turing/` unchanged.

Not wired into `src/stronghold/`. Nothing here should import from main.
"""
