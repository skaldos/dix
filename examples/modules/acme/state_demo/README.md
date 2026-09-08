# State model pressure application

This example owns a declarative state model specification and composes
`dix/state/models` only to construct its local Pydantic model type. Concrete values remain in
the application and are validated there with `model_validate()`.

Run the visible pressure path from the repository root with:

```bash
uv run --extra state python examples/run_state_demo.py
```
