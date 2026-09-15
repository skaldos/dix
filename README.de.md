# DIX

**Declarative Interface eXecutor** — explizite, lokale Komposition kleiner Python-Runtime-Graphen.

[English](README.md) · [Dokumentation](https://dix.skaldos.dev) ·
[Source](https://github.com/skaldos/dix) · [ROBA](https://github.com/skaldos/roba) ·
[Externe Module](https://github.com/skaldos/dix-modules)

> **Public Alpha:** DIX ist nutzbar und getestet, aber API und Modulformate koennen sich vor einem
> stabilen Release noch aendern. Wer darauf aufbaut, sollte einen konkreten Source-Stand pinnen.

DIX laedt explizit ausgewaehlte Source-Module, baut daraus Compositions und Applications und
exponiert ausschliesslich deklarierte lokale Python-Funktionen:

```text
explizite Modulquelle
        ↓
Composition-Graph
        ↓
Application-Graph
        ↓
explizit exponierte Python-Funktionen
```

DIX ist bewusst kein Framework, das alles entdeckt, jeden Lifecycle besitzt oder saemtliche
Semantik in einen zentralen Vertrag zieht. Ein Modul behaelt seine Fachlogik; DIX liefert eine
kleine, inspizierbare Assembly-Grenze.

## Warum DIX existiert

Kleine Tools beginnen oft als nuetzliche isolierte Funktionen und enden dann fest eingebaut in
einer CLI, einem Daemon, HTTP-Service oder einer einzelnen Anwendung. DIX trennt den
wiederverwendbaren Application-Graphen von solchen Adaptern. Dieselbe explizit exponierte Funktion
kann deshalb heute durch eine CLI und spaeter durch einen anderen lokal verantworteten Adapter
genutzt werden, ohne Transportpolitik in den Core zu ziehen.

Die entscheidende Grenze ist Verantwortung:

- **DIX Core** verantwortet deterministische Graph-Inspektion, Aufbau, Exposition und Abbau.
- **Module** verantworten Verhalten, Config-Bedeutung, Validierung und Seiteneffekte.
- **Applications** verantworten Adaption und Policy an ihrer aufrufbaren Grenze.
- **Launcher und Adapter** verantworten Prozess-, CLI-, Transport- oder UI-Belange.

## Kernbegriffe

| Begriff | Verantwortung |
| --- | --- |
| **Element** | Verarbeitet einen nativen Python-Wert durch eine explizit registrierte technische Handler-Kette. |
| **Datamodel** | Verarbeitet Mappings gegen lokal registrierte Feldschemas und liefert strukturierte Ergebnisse. Es instanziiert keine Domain-Objekte fuer den Aufrufer. |
| **Composition** | Baut einen lokalen Graphen aus Components und weiteren Compositions und exponiert nur deklarierte Funktionen. |
| **Application** | Verbindet Compositions und Applications zu einer aufrufbaren lokalen Grenze. Eine Application kann Funktionen wrappen, umbenennen oder bewusst nicht weiterreichen. |
| **Module** | Ein Source-verantwortetes Buendel aus Composition- und Application-Definitionen, das explizit inspiziert, geladen und entladen wird. |

Composition- und Application-Specs beschreiben **Graph-Assembly und Funktions-Exposition**. Sie
sind keine Wire Contracts. Die Python-Methoden der Runtime bleiben autoritativ fuer Argument- und
Ergebnissignaturen; DIX validiert, normalisiert, serialisiert, wiederholt, begrenzt oder auditiert
Aufrufe nicht stillschweigend.

## Schnellstart aus dem Source

DIX setzt derzeit Python 3.12 oder neuer voraus. Das Repository nutzt
[`uv`](https://docs.astral.sh/uv/) fuer seine reproduzierbare Entwicklungsumgebung.

```sh
git clone https://github.com/skaldos/dix.git
cd dix
uv sync --extra dev
```

Das folgende vollstaendige Beispiel laedt explizit das mitgelieferte Source-Beispiel, erzeugt einen
Application-Graphen, ruft eine exponierte Funktion auf und baut alles wieder ab:

```sh
uv run python - <<'PY'
from pathlib import Path

from dix.core import (
    ApplicationComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec

registry = create_core_component_registry()
modules = registry.require("module", ModuleComponent)
applications = registry.require("application", ApplicationComponent)

modules.load_module(Path("examples/modules/acme/demo"), module_id="acme/demo")
instance = applications.create_instance(
    ApplicationInstanceSpec(
        id="demo",
        use="acme/demo/child",
        config={},
        config_base_dir=Path.cwd(),
    ),
    owner_scope_id="readme",
)

print(instance.api.require("describe")("Skaldos"))

applications.destroy_instance("readme", "demo")
modules.unload_module("acme/demo")
PY
```

Erwartete Ausgabe:

```text
child[formatted<value:Skaldos>]
```

In diesem Beispiel wird nichts implizit entdeckt oder gestartet.

## Modulstruktur

Ein direkt ladbares Source-Modul besitzt genau eine Modulwurzel und mindestens eine Composition
oder Application:

```text
acme/example/
├── compositions/
│   └── formatter/
│       ├── composition.toml
│       └── runtime.py
└── apps/
    └── report/
        ├── app.toml
        └── runtime.py
```

Die effektiven IDs entstehen aus der expliziten Modul-ID und der lokalen Definitions-ID, zum
Beispiel `acme/example/formatter` und `acme/example/report`. Es gibt weder ein erforderliches
`module.toml` noch eine globale Modul-Registry oder automatisches Laden.

Eine minimale Composition deklariert ausschliesslich Funktionen, die Aufrufer sehen duerfen:

```toml
[composition]
id = "formatter"

[functions.format]
description = "Format one value."
```

```python
class Runtime:
    def __init__(self, *, context, config):
        self.context = context
        self.config = config

    def format(self, value: str) -> str:
        return f"formatted<{value}>"
```

Applications folgen demselben expliziten Muster und koennen Compositions oder weitere
Applications verbinden. Funktionen von Abhaengigkeiten werden nie automatisch exportiert: Die
Application muss die gewollte Grenze deklarieren oder selbst implementieren.

## Bootstrap-Launcher

`dix.bootstrap` erzeugt aus einer expliziten Launcher-Spec ein normales Python-Skript:

```sh
uv run python -m dix.bootstrap build \
  examples/launchers/my_cli.toml \
  --output /tmp/my-cli
```

Das generierte Skript enthaelt feste Modulquellen, erzeugt eine eigene Registry, laedt nur die
aufgefuehrten Module, erzeugt eine Application, ruft eine deklarierte Entry-Funktion auf und baut
den Graphen wieder ab. Der aktuelle `python_cli`-Adapter erwartet fuer diese Entry-Funktion
`list[str] -> int`; das ist ein Adaptervertrag und kein universeller DIX-Funktionsvertrag.

Das Multi-Application-CLI-Beispiel steht in
[`examples/launchers/README.md`](examples/launchers/README.md).

## First-Party-Module

Das Wheel enthaelt drei explizit ladbare Module als Package Data:

| Modul | Zweck | Extra |
| --- | --- | --- |
| `dix/cli` | Projiziert explizit uebergebene Application-APIs in einen Typer-Command-Tree. | `cli` |
| `dix/state` | Baut lokale Pydantic-basierte State-Modelle mit expliziten `get`- und `set`-Grenzen. | `state` |
| `dix/roba` | Komponiert DIX-Applications mit dem eigenstaendig verantworteten ephemeren State-Service ROBA. | `roba` |

Installiere nur die optionalen Abhaengigkeiten, die du wirklich brauchst:

```sh
uv sync --extra cli
uv sync --extra state
uv sync --extra roba
```

Mitlieferung bedeutet weder Discovery noch Autostart. Ein mitgeliefertes Modul wird explizit
aufgeloest und danach wie jede andere Source-Quelle geladen:

```python
from dix.modules import first_party_module_path

state_source = first_party_module_path("dix/state")
```

[ROBA](https://github.com/skaldos/roba) bleibt ein eigenstaendiges Projekt. Es ist ein ephemerer
Runtime-State- und Austausch-Service, kein Persistenz- oder Credential-Store.

## Externe Source-Module

Externe Module behalten ihr eigenes Repository, ihre Abhaengigkeiten, Tests,
Release-Entscheidungen und optionalen Integrationsartefakte. DIX benoetigt lediglich einen
expliziten Source-Pfad und eine Modul-ID. Dafuer ist weder ein Package Manager noch eine
Git-Submodule-Beziehung erforderlich.

Das Repository [`skaldos/dix-modules`](https://github.com/skaldos/dix-modules) demonstriert diese
Grenze. Sein Modul `skaldos/sway` ist eine reale Sway-/ROBA-Integration und bewusst weder Teil des
DIX-Wheels noch des DIX-Dependency-Graphen. Clone- und Integrationsanweisungen gehoeren in dieses
Source-Repository; DIX entdeckt es nicht automatisch.

## Oeffentliche Python-API

Die Public-Alpha-API ist bewusst schmal und nach Modulen begrenzt:

- `dix.core` und dessen deklariertes `__all__`;
- `dix.core.application` und dessen deklariertes `__all__`;
- `dix.core.composition` und dessen deklariertes `__all__`;
- `dix.core.module` und dessen deklariertes `__all__`;
- `dix.bootstrap` und dessen deklariertes `__all__`;
- `dix.modules` und dessen deklariertes `__all__`;
- `dix.__version__`.

Andere Implementierungsmodule, Package-Data-Pfade, Details des dynamischen Runtime-Ladens und
interne Repository-Strukturen werden nicht allein deshalb Public API, weil Python sie importieren
oder inspizieren kann. DIX fuehrt keine Convenience-Reexports an der Paketwurzel ein.

## Explizite Grenzen und Sicherheitsgrenze

DIX Core stellt **nicht** bereit:

- Modul-Autodiscovery oder Autostart;
- Daemon, Scheduler, Event Loop, HTTP-Server, IPC-Transport oder UI;
- Autorisierung, Retry, Timeout, Audit, Persistenz oder Deployment-Policy;
- Prozess-, Dateisystem-, Netzwerk- oder Code-Isolation;
- einen universellen Vertrag fuer Runtime-Argumente oder Serialisierung.

Python-Code einer Modul-Runtime wird **im aktuellen Prozess** importiert und ausgefuehrt. Atomare
Registry-Publikation kann verhindern, dass ein teilweise geladener Graph sichtbar wird, aber keine
Import-Seiteneffekte rueckgaengig machen und ist keine Security-Sandbox. Lade nur vertrauenswuerdigen
Code oder errichte ausserhalb von DIX eine echte Prozess- beziehungsweise Betriebssystemgrenze.

## Entwicklung

Die vollstaendige Repository-Pruefung laeuft aus einem Source-Checkout:

```sh
uv sync --extra dev --extra cli --extra state --extra roba
uv run --extra dev --extra cli --extra state --extra roba pytest -q
uv run python -W error -m compileall -f -q src modules tests examples
uv build --wheel
```

Stabiler Source importiert nie aus `unstable/`, und `unstable/` ist aus Wheels ausgeschlossen.
Synthetische Fixtures unter `tests/fixtures/` sind Testinputs und keine ausgelieferten Module.

## Lizenz

Apache License 2.0. Siehe [`LICENSE`](LICENSE).
