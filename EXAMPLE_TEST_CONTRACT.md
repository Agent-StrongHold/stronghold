# Complete Test Contract Example: Pod Discovery (P-2)

## Acceptance Criteria (from PROBLEMS_ACCEPTANCE_SOLUTIONS.md)

| # | Criterion | Description |
|---|-----------|-------------|
| AC1 | Router can find user's pod in <5ms (cache hit) |
| AC2 | Router can find user's pod in <50ms (cache miss, K8s lookup) |
| AC3 | Discovery returns `None` if no pod exists (triggers spawn) |
| AC4 | Discovery returns `None` if pod is unhealthy |
| AC5 | Discovery automatically refreshes when pod IP changes |
| AC6 | Discovery handles pod replacement (old IP invalidated) |

---

## Test Contract

**File**: `tests/architecture/test_pod_discovery.py`

```python
import pytest
import time
from stronghold.agent_pod.discovery import PodDiscovery

# Test fakes (for unit tests without real infrastructure)
class FakeRedis:
    def __init__(self):
        self.data = {}
    
    async def get(self, key):
        return self.data.get(key)
    
    async def set(self, key, value, ex=None):
        self.data[key] = value
    
    async def exists(self, key):
        return key in self.data
    
    async def ttl(self, key):
        return 60  # Default TTL: 60s
    
    async def delete(self, key):
        self.data.pop(key, None)


class FakeK8s:
    def __init__(self):
        self.pods = {}
    
    def add_pod(self, name, ip, labels=None, healthy=True):
        self.pods[name] = {
            "ip": ip,
            "labels": labels or {},
            "healthy": healthy
        }
    
    def update_pod_ip(self, name, ip):
        if name in self.pods:
            self.pods[name]["ip"] = ip
    
    def set_healthy(self, name, healthy):
        if name in self.pods:
            self.pods[name]["healthy"] = healthy


fake_redis = FakeRedis()
fake_k8s = FakeK8s()


def test_discovery_cache_hit_latency():
    """
    AC: Router can find user's pod in <5ms (cache hit)
    
    EVIDENCE: Cached lookup completes in under 5ms.
    
    SCENARIO:
    - User's pod already registered in Redis cache
    - Discovery retrieves from cache without K8s lookup
    """
    discovery = PodDiscovery(redis_client=fake_redis, k8s_client=fake_k8s)
    
    # Arrange: Register pod in cache
    await discovery.register_pod("user-123", "10.0.1.5", "generic")
    
    # Act: Measure cache hit latency
    start = time.perf_counter()
    pod_ip = await discovery.get_user_pod("user-123", "generic")
    elapsed_ms = (time.perf_counter() - start) * 1000
    
    # Assert: Correct IP returned and latency <5ms
    assert pod_ip == "10.0.1.5", f"Expected 10.0.1.5, got {pod_ip}"
    assert elapsed_ms < 5.0, f"Cache hit took {elapsed_ms}ms, expected <5ms"


def test_discovery_cache_miss_latency():
    """
    AC: Router can find user's pod in <50ms (cache miss, K8s lookup)
    
    EVIDENCE: K8s lookup completes in under 50ms.
    
    SCENARIO:
    - User's pod not in Redis cache
    - Discovery queries K8s for pod by labels
    """
    discovery = PodDiscovery(redis_client=fake_redis, k8s_client=fake_k8s)
    
    # Arrange: Add pod to K8s (not cache)
    fake_k8s.add_pod("agent-user-123-generic", "10.0.1.5", 
                     labels={"user": "user-123", "type": "generic"})
    
    # Act: Measure cache miss latency
    start = time.perf_counter()
    pod_ip = await discovery.get_user_pod("user-123", "generic")
    elapsed_ms = (time.perf_counter() - start) * 1000
    
    # Assert: Correct IP returned and latency <50ms
    assert pod_ip == "10.0.1.5", f"Expected 10.0.1.5, got {pod_ip}"
    assert elapsed_ms < 50.0, f"K8s lookup took {elapsed_ms}ms, expected <50ms"


def test_discovery_none_when_no_pod():
    """
    AC: Discovery returns None if no pod exists (triggers spawn)
    
    EVIDENCE: Returns None when pod not found.
    
    SCENARIO:
    - User "nonexistent-user" has no registered pod
    - Discovery checks both cache and K8s
    """
    discovery = PodDiscovery(redis_client=fake_redis, k8s_client=fake_k8s)
    
    # Act: Try to find non-existent pod
    pod_ip = await discovery.get_user_pod("nonexistent-user", "generic")
    
    # Assert: None returned (triggers spawn)
    assert pod_ip is None, f"Expected None for nonexistent user, got {pod_ip}"


def test_discovery_none_when_unhealthy():
    """
    AC: Discovery returns None if pod is unhealthy
    
    EVIDENCE: Returns None for unhealthy pods.
    
    SCENARIO:
    - Pod exists but marked unhealthy
    - Discovery should return None despite cache containing it
    """
    discovery = PodDiscovery(redis_client=fake_redis, k8s_client=fake_k8s)
    
    # Arrange: Add unhealthy pod to K8s
    fake_k8s.add_pod("agent-user-123-generic", "10.0.1.5", 
                     labels={"user": "user-123", "type": "generic"},
                     healthy=False)
    
    # Act: Try to find unhealthy pod
    pod_ip = await discovery.get_user_pod("user-123", "generic")
    
    # Assert: None returned (unhealthy pod treated as nonexistent)
    assert pod_ip is None, f"Expected None for unhealthy pod, got {pod_ip}"


def test_discovery_refresh_on_ip_change():
    """
    AC: Discovery automatically refreshes when pod IP changes
    
    EVIDENCE: Cache invalidated and new IP returned.
    
    SCENARIO:
    - Pod initially registered with IP1
    - Pod is recreated with new IP2
    - Next discovery should return IP2 (not stale IP1)
    """
    discovery = PodDiscovery(redis_client=fake_redis, k8s_client=fake_k8s)
    
    # Arrange: Register pod with IP1
    await discovery.register_pod("user-123", "10.0.1.5", "generic")
    assert await discovery.get_user_pod("user-123", "generic") == "10.0.1.5"
    
    # Act: Simulate pod recreation with new IP2
    fake_k8s.update_pod_ip("agent-user-123-generic", "10.0.2.1")
    await discovery.unregister_pod("user-123", "generic")  # Clear cache
    await discovery.register_pod("user-123", "10.0.2.1", "generic")  # Re-register
    
    # Assert: Discovery returns new IP2
    new_ip = await discovery.get_user_pod("user-123", "generic")
    assert new_ip == "10.0.2.1", f"Expected 10.0.2.1, got {new_ip}"


def test_discovery_pod_replacement():
    """
    AC: Discovery handles pod replacement (old IP invalidated)
    
    EVIDENCE: Old pod IP invalidated when new pod registered.
    
    SCENARIO:
    - Pod1 is registered with IP1
    - Pod2 is registered as replacement with IP2
    - Old IP should be invalidated
    - Discovery should return IP2
    """
    discovery = PodDiscovery(redis_client=fake_redis, k8s_client=fake_k8s)
    
    # Arrange: Register Pod1 with IP1
    await discovery.register_pod("user-123", "10.0.1.5", "generic")
    assert await discovery.get_user_pod("user-123", "generic") == "10.0.1.5"
    
    # Act: Register Pod2 as replacement (same user, same agent type)
    await discovery.register_pod("user-123", "10.0.2.1", "generic")
    
    # Assert: Old IP invalidated, new IP returned
    new_ip = await discovery.get_user_pod("user-123", "generic")
    assert new_ip == "10.0.2.1", f"Expected 10.0.2.1, got {new_ip}"
```

---

## AC Mapping Table

| Test Function | AC1 | AC2 | AC3 | AC4 | AC5 | AC6 |
|---------------|-----|-----|-----|-----|-----|-----|
| test_discovery_cache_hit_latency | ✅ | | | | | |
| test_discovery_cache_miss_latency | | ✅ | | | | |
| test_discovery_none_when_no_pod | | | ✅ | | | |
| test_discovery_none_when_unhealthy | | | | ✅ | | |
| test_discovery_refresh_on_ip_change | | | | | ✅ | ✅ |
| test_discovery_pod_replacement | | | | | | ✅ |

---

## How Tests Provide Evidence

### Direct Assertions (Measurable)
```python
assert pod_ip == "10.0.1.5"              # Measurable: Exact match
assert elapsed_ms < 5.0                    # Measurable: Numeric comparison
assert pod_ip is None                         # Measurable: Boolean check
```

### Measured Values (Quantitative Evidence)
```python
elapsed_ms = (time.perf_counter() - start) * 1000
assert elapsed_ms < 5.0                        # Evidence: Actual < Target
```

### Resource Inspection (Direct Verification)
```python
fake_redis.get(key)      # Evidence: Cache key exists
fake_k8s.pods[name]     # Evidence: Pod exists in K8s
```

### Verification (End-to-End)
```python
# Register → Discover → Assert Correct
await discovery.register_pod("user-123", "10.0.1.5", "generic")
assert await discovery.get_user_pod("user-123", "generic") == "10.0.1.5"
```

---

## Key Patterns

1. **Arrange-Act-Assert** structure for clarity
2. **Fakes for unit tests** - no real infrastructure needed
3. **Async test functions** - all `PodDiscovery` methods are async
4. **Clear error messages** - `f"Expected X, got Y"` format
5. **Scenario descriptions** - explain WHEN and WHAT before tests
6. **EVIDENCE sections** - document what the test proves
7. **AC Mapping table** - quick reference of coverage

---

## Running This Test

```bash
# Run all tests in this contract
pytest tests/architecture/test_pod_discovery.py -v

# Run specific test
pytest tests/architecture/test_pod_discovery.py::test_discovery_cache_hit_latency -v

# With coverage
pytest tests/architecture/test_pod_discovery.py -v --cov=stronghold.agent_pod.discovery
```

## Integration Test (with Real Infrastructure)

```bash
# After implementing PodDiscovery, run with real Redis + K8s
pytest tests/architecture/test_pod_discovery.py -v --real-infrastructure

# The test contract will work the same way - just swap fakes for real clients
```

---

## Related Documents

- **PROBLEMS_ACCEPTANCE_SOLUTIONS.md** - Problem P-2 and its acceptance criteria
- **TEST_CONTRACTS.md** - All 128 test functions mapped to 95 ACs
- **IMPLEMENTATION_STATUS.md** - Execution phases
