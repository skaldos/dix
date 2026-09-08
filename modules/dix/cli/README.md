# DIX CLI module

First-party adapters for building command-line applications from explicit DIX application graphs.

Install the optional runtime dependency with:

```bash
pip install 'dix[cli]'
```

Resolve this module explicitly from Python with:

```python
from dix.modules import first_party_module_path

path = first_party_module_path("dix/cli")
```

Resolving a path neither loads the module nor creates an application graph.
