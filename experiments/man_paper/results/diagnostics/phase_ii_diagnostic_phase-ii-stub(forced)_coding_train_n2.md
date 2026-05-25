# Phase II diagnostic

**LLM:** `phase-ii-stub(forced)` (stub=True)
**Family:** `coding_train`
**Success rate:** 1.00
**Mean reward:** 1.00
**Split guard:** n(c-1e9f82cccb1c)=2 < n_min=24

## Scenarios

| Scenario | OK | Reward | Active | Response excerpt |
| --- | --- | --- | --- | --- |
| `ct-json` | True | 1.00 | `c-1e9f82cccb1c` | Use json.loads for parsing a JSON string. https://docs.python.org/3/library/json.html [1]. |
| `ct-fib` | True | 1.00 | `c-1e9f82cccb1c` | def fibonacci(n: int) -> int: if n <= 1: return n return fibonacci(n - 1) + fibonacci(n - 2) https://docs.python.org/3/ [1]. |

## Full Responses

### ct-json

User: How do I parse a JSON string in Python?

```text
Use json.loads for parsing a JSON string. https://docs.python.org/3/library/json.html [1].
```

### ct-fib

User: Write a recursive Fibonacci function in Python.

```text
def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
https://docs.python.org/3/ [1].
```
