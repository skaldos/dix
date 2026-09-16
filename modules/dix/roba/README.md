# dix/roba

Optional DIX adapter module for the public Python API of the independent `roba` package.

The module is explicit: callers load `dix/roba` through the normal DIX module component. It does
not autoload and it does not make `roba` a DIX base dependency.

The initial `config` composition owns one isolated, full-model local configuration value and exposes
`get`, `set`, and `environment`. It reads neither `roba.toml` nor inherited `ROBA_*` settings.

`DIX_ROBA_RUNTIME_ROOT` and `DIX_ROBA_LOGS_ROOT` are explicit process-wide defaults for DIX ROBA
applications and compositions. They let separate DIX consumers address the same non-default ROBA
daemon without inheriting arbitrary `ROBA_*` configuration. Named application arguments remain
stronger for the individual invocation. Without either override, the established
`~/.roba/runtime` and `~/.roba/logs` defaults remain unchanged.
