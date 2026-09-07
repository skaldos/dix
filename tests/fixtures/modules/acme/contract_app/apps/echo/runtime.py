class Runtime:
    def __init__(self, *, context, config, worker):
        self.context = context
        self.config = config
        self._worker = worker

    def echo(self, value):
        return self._worker.echo(value)

    def internal(self):
        return "not exposed"
