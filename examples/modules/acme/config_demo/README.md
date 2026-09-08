# Config model pressure application

This example owns a declarative configuration model specification and composes
`dix/config/pydantic` only to construct its local Pydantic model type. Concrete values remain in
the application and are validated there with `model_validate()`.

Run the visible pressure path from the repository root with:

```bash
uv run --extra config python examples/run_config_demo.py
```
