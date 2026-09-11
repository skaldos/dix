from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import create_model


class FakeModels:
    def require(self, function_id: str) -> Callable[..., object]:
        assert function_id == "resolve"

        def resolve(spec: Mapping[str, object]) -> type[object]:
            fields = spec["fields"]
            assert isinstance(fields, Mapping)
            definitions = {}
            for name, value in fields.items():
                assert isinstance(value, Mapping)
                definitions[name] = (str, ...)
            return create_model(str(spec["name"]), **definitions)

        return resolve


class FakeContext:
    def __init__(
        self,
        state: dict[str, object],
        *,
        credentials_error: Exception | None = None,
        fail_on: str | None = None,
    ) -> None:
        self.state_value = dict(state)
        self.credentials_error = credentials_error
        self.fail_on = fail_on
        self.calls: list[tuple[str, ...]] = []
        self.writes: list[tuple[str, object]] = []
        self.created = False

    def state(self) -> dict[str, object]:
        self.calls.append(("state",))
        return dict(self.state_value)

    def set(self, key: str, value: object) -> None:
        self.writes.append((key, value))
        if key == self.fail_on:
            raise RuntimeError(f"{key} write failed")
        self.state_value[key] = value


class FakeControl:
    def __init__(self, remote: FakeContext) -> None:
        self.remote = remote

    def require(self, function_id: str) -> Callable[..., object]:
        assert function_id == "context_credentials"

        def credentials(context_id: str) -> dict[str, str]:
            assert context_id == "shared"
            if self.remote.credentials_error is not None:
                raise self.remote.credentials_error
            return {"context_locator": "unix:/tmp/fake-context.sock", "owner_token": "owner"}

        return credentials
