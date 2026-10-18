---
name: twin-search-methods
description: Search the twin for duty candidates and verify any answer with math tools. Use after the problem is formulated and before reporting trade-offs.
---

# Twin search methods

## Procedure

1. Call `optimization_search_duty` with the goal. It returns up to five safe candidates.
2. Check your preferred candidate with `optimization_evaluate_candidate`. Confirm it recovers, is safe and improves on the baseline error.
3. If your own reasoning suggests a value the search did not list, evaluate it the same way before quoting it.

## Rules

- Never report a value you did not evaluate.
- Fuel and scrap numbers are placeholder proxies. Use them only to compare candidates.
