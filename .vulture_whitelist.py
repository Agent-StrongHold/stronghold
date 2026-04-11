# Vulture whitelist — intentionally unused names
#
# Usage in CI: vulture src/stronghold/ .vulture_whitelist.py --min-confidence 80
#
# Every entry is a name vulture would otherwise flag but which is used
# implicitly: Protocol stub parameters (part of the interface contract),
# context manager __exit__ args (PEP 343 required signature), etc.

# Protocol stub parameters — interface documentation, not dead code
agent_type  # src/stronghold/protocols/agent_pod.py:60,88,109
pod_name  # src/stronghold/protocols/agent_pod.py:89,110
generation  # src/stronghold/protocols/agent_pod.py:91
table  # src/stronghold/protocols/data.py:30
deployment_name  # src/stronghold/protocols/mcp.py:70
team  # src/stronghold/protocols/memory.py:83
ref  # src/stronghold/protocols/secrets.py:56,79
required_permissions  # src/stronghold/tools/decorator.py:19

# __exit__ context manager signature (PEP 343 required)
exc_tb  # src/stronghold/protocols/tracing.py:20
        # src/stronghold/tracing/noop.py:21
        # src/stronghold/tracing/phoenix_backend.py:41
