# Phase II diagnostic

**LLM:** `bai/gpt-5.2` (stub=False)
**Family:** `coding_train`
**Success rate:** 0.50
**Mean reward:** 0.75
**Split guard:** n(concern_self_evolving_agent_rmsp)=2 < n_min=24

## Scenarios

| Scenario | OK | Reward | Active | Response excerpt |
| --- | --- | --- | --- | --- |
| `ct-json` | False | 0.50 | `concern_self_evolving_agent_rmsp` | Use Python’s built-in `json` module. ```python import json s = '{"name": "Ada", "age": 36, "active": true, "scores": [10, 20]}' data = json.loads(s) # JSON string -> Python object  |
| `ct-fib` | True | 1.00 | `concern_self_evolving_agent_rmsp` | ```python def fib(n: int) -> int: if n < 0: raise ValueError("n must be non-negative") if n < 2: # fib(0)=0, fib(1)=1 return n return fib(n - 1) + fib(n - 2) ``` |

## Full Responses

### ct-json

User: How do I parse a JSON string in Python?

```text
Use Python’s built-in `json` module.

```python
import json

s = '{"name": "Ada", "age": 36, "active": true, "scores": [10, 20]}'
data = json.loads(s)   # JSON string -> Python object (dict/list/etc.)

print(data["name"])    # "Ada"
print(data["scores"])  # [10, 20]
```

Notes:
- `json.loads()` parses a **string**.  
- `json.load()` parses JSON from a **file-like object**:

```python
import json

with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)
```
```

### ct-fib

User: Write a recursive Fibonacci function in Python.

```text
```python
def fib(n: int) -> int:
    if n < 0:
        raise ValueError("n must be non-negative")
    if n < 2:          # fib(0)=0, fib(1)=1
        return n
    return fib(n - 1) + fib(n - 2)
```
```
