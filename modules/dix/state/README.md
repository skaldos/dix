# DIX state module

First-party adapters for owner-controlled state models.

Install the optional runtime dependency with:

```bash
pip install 'dix[state]'
```

Resolve this module explicitly from Python with:

```python
from dix.modules import first_party_module_path

path = first_party_module_path("dix/state")
```

Resolving a path neither loads the module nor creates a composition graph. The module does not
load state values or own their source.

The `dix/state/models` composition exposes `resolve(spec)`. Its owner supplies a Python mapping:

```python
spec = {
    "name": "ServiceState",
    "fields": {
        "service": {
            "type": "string",
            "help": "Name of the configured service.",
        },
        "enabled": {"type": "boolean", "default": True},
        "renderer": {
            "type": "model",
            "name": "RendererState",
            "fields": {
                "theme": {"type": "string"},
            },
        },
    },
}

StateModel = resolve(spec)
state = StateModel.model_validate(values)
```

Supported field types are `any`, `string`, `integer`, `number`, `boolean`, `object`, `array`, and
recursive `model`. A missing `default` makes a field required. `help` becomes Pydantic field
description metadata. `object` and `array` intentionally remain unstructured in this first slice.

The resolver only constructs a model type. The caller owns values, sources, errors, merge rules,
and lifecycle. Every call constructs an independent model type; there is no registry or cache.
