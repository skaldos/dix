class Runtime:
    def __init__(self, *, context, config):
        self.context = context
        self.config = config

    def main(self, arguments):
        name = arguments[0] if arguments else "World"
        print(f"Hello {name}")
        return 0
