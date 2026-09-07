class Runtime:
    def __init__(self, *, context, config):
        self.context = context
        self.config = config

    def echo(self, value):
        return value

    def internal(self):
        return "not exposed"
