# Refactoring Note: Improving Type Safety and Code Clarity in DXLinkManager

## Current Implementation

In the `DXLinkManager` class, the websocket (and similar attributes) are stored as Optional types. To safely access methods on these attributes, we currently use the following pattern:

```python
assert self.websocket is not None, "websocket should be initialized"
ws = self.websocket
await ws.send(...)
```

This assert/assignment pattern narrows the type from `Optional[ClientConnection]` to `ClientConnection` so that static type checkers (like mypy) don't raise errors regarding union attributes.

## Alternatives and Recommendations

While the assert/assignment method is common, it can seem a bit hacky. Here are some alternatives to consider:

1. **Eager Initialization**

   - Ensure that `self.websocket` (and other similar attributes) are initialized early in the lifecycle of the object so that they are never `None` when methods that use them are called.

2. **Factory Pattern**

   - Use a dedicated factory or class method that creates and returns a fully initialized instance of `DXLinkManager` with all required attributes set, eliminating the need for later type narrowing.

3. **Explicit Conditional Handling**

   - Replace the assert with an explicit if-check that raises a clear exception if the attribute is `None`:

   ```python
   if self.websocket is None:
       raise RuntimeError("Websocket was expected to be initialized but wasn't.")
   ws = self.websocket
   ```

   This approach makes the error handling explicit, ensuring that failures are caught early and in a controlled manner.

## Recommendation

Evaluate the initialization process of `DXLinkManager` to ensure that its critical attributes (like `websocket`) are reliably set before they are used. If this refactoring is feasible, it could remove the need for repeated type narrowing via asserts.

For now, the assert/assignment pattern is acceptable and is a common practice in Python when using type hints, provided that the design guarantees the attribute is not `None` at the point of use.

**Action:** Review the design of `DXLinkManager` during the next refactoring cycle to explore if eager initialization or the factory pattern can be implemented to improve robustness and code clarity.

---

*Documented on [current date].*
