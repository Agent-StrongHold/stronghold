"""Test regex parsing."""

import re

test_result = '{"passing": 10, "failing": 40, "coverage": "20%"}'

passing_match = re.search(r"(\d+)\s+passed", test_result)
failing_match = re.search(r"(\d+)\s+failed", test_result)

passing_count = int(passing_match.group(1)) if passing_match else 0
failing_count = int(failing_match.group(1)) if failing_match else 0

print(f"Test result: {test_result}")
print(f"Passing: {passing_count}, Failing: {failing_count}")
print(f"failing_count == 0: {failing_count == 0}")
