# DIX config module

First-party adapters for owner-controlled configuration models.

Install the optional runtime dependency with:

```bash
pip install 'dix[config]'
```

Resolve this module explicitly from Python with:

```python
from dix.modules import first_party_module_path

path = first_party_module_path("dix/config")
```

Resolving a path neither loads the module nor creates a composition graph. The module does not
load configuration values or own their source.
