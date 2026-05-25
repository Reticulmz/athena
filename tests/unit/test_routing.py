"""Tests for RouteGroup routing infrastructure.

Validates:
- Req 1.1: @route decorator registers method-to-key mapping in _ROUTE_KEYS
- Req 1.2: __init_subclass__ auto-collects decorated methods into __routes__
- Req 1.3: get_routes() returns (key, bound_method) iterator
- Req 1.4: RouteGroup supports constructor DI (arbitrary __init__)
"""

from __future__ import annotations

import types

from osu_server.transports.bancho.routing import RouteGroup, get_route_registry, route


class TestRouteDecorator:
    """Req 1.1: @route(key) registers in _ROUTE_KEYS module dict."""

    def test_route_registers_function_in_route_keys(self) -> None:
        """Decorated function appears in _ROUTE_KEYS with its key."""

        @route("test_key")
        async def handler(_self: object, _payload: bytes, _user_id: int) -> None:
            pass

        registry = get_route_registry()
        assert handler in registry
        assert registry[handler] == "test_key"

    def test_route_preserves_original_function(self) -> None:
        """Decorator returns the original function unchanged."""

        async def original(_self: object, _payload: bytes, _user_id: int) -> None:
            pass

        decorated = route("some_key")(original)
        assert decorated is original

    def test_route_does_not_add_attributes_to_method(self) -> None:
        """Decorator must NOT add attributes to the function itself."""

        @route("attr_check")
        async def handler(_self: object) -> None:
            pass

        # No __route_key__ or similar attribute should be added
        assert not hasattr(handler, "__route_key__")
        assert not hasattr(handler, "_route_key")
        assert not hasattr(handler, "route_key")

    def test_route_with_different_key_types(self) -> None:
        """Keys can be any hashable type (enum, str, int, etc.)."""

        @route(42)
        async def handler_int(_self: object) -> None:
            pass

        registry = get_route_registry()
        assert registry[handler_int] == 42  # noqa: PLR2004


class TestInitSubclass:
    """Req 1.2: __init_subclass__ collects decorated methods into __routes__."""

    def test_subclass_has_routes_classvar(self) -> None:
        """Subclass of RouteGroup gets __routes__ populated at class definition."""

        class MyGroup(RouteGroup):
            @route("key_a")
            async def method_a(self, _payload: bytes, _user_id: int) -> None:
                pass

        assert hasattr(MyGroup, "__routes__")
        assert "key_a" in MyGroup.__routes__

    def test_routes_maps_key_to_method_name(self) -> None:
        """__routes__ maps key -> method name string."""

        class MyGroup(RouteGroup):
            @route("key_b")
            async def method_b(self, _payload: bytes, _user_id: int) -> None:
                pass

        assert MyGroup.__routes__["key_b"] == "method_b"

    def test_multiple_decorated_methods_collected(self) -> None:
        """All @route-decorated methods in a class are collected."""

        class MyGroup(RouteGroup):
            @route("first")
            async def handle_first(self) -> None:
                pass

            @route("second")
            async def handle_second(self) -> None:
                pass

        expected_count = 2
        assert len(MyGroup.__routes__) == expected_count
        assert MyGroup.__routes__["first"] == "handle_first"
        assert MyGroup.__routes__["second"] == "handle_second"

    def test_undecorated_methods_not_collected(self) -> None:
        """Methods without @route are NOT included in __routes__."""

        class MyGroup(RouteGroup):
            @route("decorated")
            async def handle_decorated(self) -> None:
                pass

            async def handle_plain(self) -> None:
                pass

            def sync_method(self) -> None:
                pass

        assert len(MyGroup.__routes__) == 1
        assert "handle_plain" not in MyGroup.__routes__.values()
        assert "sync_method" not in MyGroup.__routes__.values()

    def test_only_own_class_methods_collected(self) -> None:
        """vars(cls) scans only the defining class, not inherited methods."""

        class Parent(RouteGroup):
            @route("parent_key")
            async def parent_handler(self) -> None:
                pass

        class Child(Parent):
            @route("child_key")
            async def child_handler(self) -> None:
                pass

        # Child should only have its own route, not parent's
        assert "child_key" in Child.__routes__
        assert "parent_key" not in Child.__routes__

    def test_empty_subclass_has_empty_routes(self) -> None:
        """A subclass with no decorated methods gets an empty __routes__."""

        class EmptyGroup(RouteGroup):
            async def plain_method(self) -> None:
                pass

        assert EmptyGroup.__routes__ == {}


class TestGetRoutes:
    """Req 1.3: get_routes() returns (key, bound_method) iterator."""

    def test_get_routes_returns_iterator(self) -> None:
        """get_routes() yields tuples of (key, bound_method)."""

        class MyGroup(RouteGroup):
            @route("the_key")
            async def the_handler(self) -> None:
                pass

        instance = MyGroup()
        routes = list(instance.get_routes())
        assert len(routes) == 1
        key, _bound_method = routes[0]
        assert key == "the_key"

    def test_get_routes_returns_bound_methods(self) -> None:
        """The methods returned by get_routes() are bound to the instance."""

        class MyGroup(RouteGroup):
            @route("bound_check")
            async def handler(self) -> None:
                pass

        instance = MyGroup()
        routes = list(instance.get_routes())
        _, method = routes[0]
        # A bound method's __self__ should reference the instance
        assert isinstance(method, types.MethodType)
        assert method.__self__ is instance

    def test_get_routes_multiple(self) -> None:
        """get_routes() yields all registered routes."""

        class MyGroup(RouteGroup):
            @route("alpha")
            async def handle_alpha(self) -> None:
                pass

            @route("beta")
            async def handle_beta(self) -> None:
                pass

        instance = MyGroup()
        routes = dict(instance.get_routes())
        expected_count = 2
        assert len(routes) == expected_count
        assert "alpha" in routes
        assert "beta" in routes

    def test_get_routes_methods_are_callable(self) -> None:
        """Bound methods from get_routes() are callable awaitables."""

        class MyGroup(RouteGroup):
            def __init__(self) -> None:
                self.called: bool = False

            @route("call_check")
            async def handler(self) -> None:
                self.called = True

        instance = MyGroup()
        routes = dict(instance.get_routes())
        # Verify it's callable
        assert callable(routes["call_check"])

    async def test_get_routes_method_execution(self) -> None:
        """Bound methods from get_routes() can be awaited and execute correctly."""

        class MyGroup(RouteGroup):
            def __init__(self) -> None:
                self.called: bool = False

            @route("exec_check")
            async def handler(self) -> None:
                self.called = True

        instance = MyGroup()
        routes = dict(instance.get_routes())
        await routes["exec_check"]()
        assert instance.called is True

    def test_get_routes_empty_group(self) -> None:
        """get_routes() on a group with no routes yields nothing."""

        class EmptyGroup(RouteGroup):
            pass

        instance = EmptyGroup()
        assert list(instance.get_routes()) == []


class TestConstructorDI:
    """Req 1.4: RouteGroup supports constructor dependency injection."""

    def test_subclass_with_custom_init(self) -> None:
        """Subclass can define __init__ with arbitrary dependencies."""

        class MyGroup(RouteGroup):
            def __init__(self, dep_a: str, dep_b: int) -> None:
                self.dep_a: str = dep_a
                self.dep_b: int = dep_b

            @route("with_deps")
            async def handler(self) -> None:
                pass

        dep_b_value = 42
        instance = MyGroup("hello", dep_b_value)
        assert instance.dep_a == "hello"
        assert instance.dep_b == dep_b_value

    async def test_handler_can_access_injected_deps(self) -> None:
        """Handler methods can use dependencies injected via __init__."""
        results: list[str] = []

        class MyGroup(RouteGroup):
            def __init__(self, sink: list[str]) -> None:
                self.sink: list[str] = sink

            @route("dep_access")
            async def handler(self) -> None:
                self.sink.append("invoked")

        instance = MyGroup(results)
        routes = dict(instance.get_routes())
        await routes["dep_access"]()
        assert results == ["invoked"]
