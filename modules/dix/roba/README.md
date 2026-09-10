# dix/roba

Optional DIX adapter module for the public Python API of the independent `roba` package.

The module is explicit: callers load `dix/roba` through the normal DIX module component. It does
not autoload and it does not make `roba` a DIX base dependency.

The initial `config` composition owns one isolated, full-model local configuration value and exposes
`get`, `set`, and `environment`. It reads neither `roba.toml` nor inherited `ROBA_*` settings.
