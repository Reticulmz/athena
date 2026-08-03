"""RouteGroupのdecorator registryとbound route取得を検証するmodule.

route decoratorによるkey登録とsubclass収集およびconstructor dependency injectionを対象にする.
"""

from __future__ import annotations

import types

from osu_server.transports.stable.bancho.routing import RouteGroup, get_route_registry, route


class TestRouteDecorator:
    """route decoratorがfunctionとrouting keyを登録することを検証するtest群."""

    def test_route_registers_function_in_route_keys(self) -> None:
        """このroute decoratorがfunctionを指定keyでregistryへ登録することを検証する.

        test_keyを渡してasync handlerをdecorateしregistryから同じfunctionとkeyの対応を
        取得できることを確認する.

        Returns:
            None: route registry登録の検証を完了する.
        """

        @route("test_key")
        async def handler(_self: object, _payload: bytes, _user_id: int) -> None:
            """このroute registry登録だけを検証するasync handler.

            Args:
                _self (object): bound instanceを表すplaceholder.
                _payload (bytes): packet payloadを表すplaceholder.
                _user_id (int): packet送信user IDを表すplaceholder.

            Returns:
                None: 副作用を持たずに完了する.
            """

        registry = get_route_registry()
        assert handler in registry
        assert registry[handler] == "test_key"

    def test_route_preserves_original_function(self) -> None:
        """このroute decoratorが元のfunction objectを返すことを検証する.

        undecorated async functionへsome_keyのdecoratorを適用し戻り値が元のfunctionと
        同一であることを確認する.

        Returns:
            None: function identity保持の検証を完了する.
        """

        async def original(_self: object, _payload: bytes, _user_id: int) -> None:
            """このdecorator identityを検証する元のasync function.

            Args:
                _self (object): bound instanceを表すplaceholder.
                _payload (bytes): packet payloadを表すplaceholder.
                _user_id (int): packet送信user IDを表すplaceholder.

            Returns:
                None: 副作用を持たずに完了する.
            """

        decorated = route("some_key")(original)
        assert decorated is original

    def test_route_does_not_add_attributes_to_method(self) -> None:
        """このroute decoratorがfunction objectへroute key属性を追加しないことを検証する.

        attr_checkでhandlerをdecorateし候補となる三つのattributeがすべて不在であることを確認する.

        Returns:
            None: function attribute非追加の検証を完了する.
        """

        @route("attr_check")
        async def handler(_self: object) -> None:
            """このfunctionのattribute非追加を検証するasync handler.

            Args:
                _self (object): bound instanceを表すplaceholder.

            Returns:
                None: 副作用を持たずに完了する.
            """

        # No __route_key__ or similar attribute should be added
        assert not hasattr(handler, "__route_key__")
        assert not hasattr(handler, "_route_key")
        assert not hasattr(handler, "route_key")

    def test_route_with_different_key_types(self) -> None:
        """このroute decoratorが整数keyをregistryへ保持することを検証する.

        整数42でhandlerをdecorateしregistryが同じ整数をfunctionのroute keyとして返すことを確認する.

        Returns:
            None: hashable key登録の検証を完了する.
        """

        @route(42)
        async def handler_int(_self: object) -> None:
            """整数route keyを検証するasync handler.

            Args:
                _self (object): bound instanceを表すplaceholder.

            Returns:
                None: 副作用を持たずに完了する.
            """

        registry = get_route_registry()
        assert registry[handler_int] == 42


class TestInitSubclass:
    """RouteGroup.__init_subclass__によるdecorated method収集を検証するtest群."""

    def test_subclass_has_routes_classvar(self) -> None:
        """RouteGroup subclassがclass定義時に__routes__を持つことを検証する.

        key_aのdecorated methodを持つsubclassを定義し__routes__の存在とkey_a登録を確認する.

        Returns:
            None: class route集合生成の検証を完了する.
        """

        class MyGroup(RouteGroup):
            """key_aのrouteを持つsubclass収集検証用group."""

            @route("key_a")
            async def method_a(self, _payload: bytes, _user_id: int) -> None:
                """key_aに対応する収集検証用method.

                Args:
                    _payload (bytes): packet payloadを表すplaceholder.
                    _user_id (int): packet送信user IDを表すplaceholder.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        assert hasattr(MyGroup, "__routes__")
        assert "key_a" in MyGroup.__routes__

    def test_routes_maps_key_to_method_name(self) -> None:
        """__routes__がroute keyをmethod名へ対応付けることを検証する.

        key_bのdecorated methodを持つsubclassを定義し__routes__からmethod_bという文字列を
        取得できることを確認する.

        Returns:
            None: route keyとmethod名の対応検証を完了する.
        """

        class MyGroup(RouteGroup):
            """key_bのrouteを持つmethod名収集検証用group."""

            @route("key_b")
            async def method_b(self, _payload: bytes, _user_id: int) -> None:
                """key_bに対応するmethod名検証用method.

                Args:
                    _payload (bytes): packet payloadを表すplaceholder.
                    _user_id (int): packet送信user IDを表すplaceholder.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        assert MyGroup.__routes__["key_b"] == "method_b"

    def test_multiple_decorated_methods_collected(self) -> None:
        """複数のdecorated methodがすべて__routes__へ収集されることを検証する.

        firstとsecondの二routeを持つsubclassを定義しroute数と各method名が期待値に一致することを確認する.

        Returns:
            None: 複数route収集の検証を完了する.
        """

        class MyGroup(RouteGroup):
            """firstとsecondのrouteを持つ複数収集検証用group."""

            @route("first")
            async def handle_first(self) -> None:
                """複数収集のfirst routeを表す検証用method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

            @route("second")
            async def handle_second(self) -> None:
                """複数収集のsecond routeを表す検証用method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        expected_count = 2
        assert len(MyGroup.__routes__) == expected_count
        assert MyGroup.__routes__["first"] == "handle_first"
        assert MyGroup.__routes__["second"] == "handle_second"

    def test_undecorated_methods_not_collected(self) -> None:
        """このroute decoratorを持たないmethodが__routes__へ収集されないことを検証する.

        decoratedとplainおよびsync methodを持つsubclassを定義しdecorated routeだけが
        収集されることを確認する.

        Returns:
            None: undecorated method除外の検証を完了する.
        """

        class MyGroup(RouteGroup):
            """decoratedとundecorated methodを混在させる収集検証用group."""

            @route("decorated")
            async def handle_decorated(self) -> None:
                """このdecorated routeとして収集されるasync method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

            async def handle_plain(self) -> None:
                """このroute decoratorを持たないasync method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

            def sync_method(self) -> None:
                """このroute decoratorを持たない同期method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        assert len(MyGroup.__routes__) == 1
        assert "handle_plain" not in MyGroup.__routes__.values()
        assert "sync_method" not in MyGroup.__routes__.values()

    def test_only_own_class_methods_collected(self) -> None:
        """subclassの__routes__が親から継承したmethodを含まないことを検証する.

        parent_keyとchild_keyを別classへ定義しChildのroute集合にchild_keyだけがあることを確認する.

        Returns:
            None: own class route限定の検証を完了する.
        """

        class Parent(RouteGroup):
            """parent_keyのrouteを持つ継承検証用親group."""

            @route("parent_key")
            async def parent_handler(self) -> None:
                """parent_keyに対応する親groupのmethod.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        class Child(Parent):
            """child_keyのrouteを持つ継承検証用子group."""

            @route("child_key")
            async def child_handler(self) -> None:
                """child_keyに対応する子groupのmethod.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        # Child should only have its own route, not parent's
        assert "child_key" in Child.__routes__
        assert "parent_key" not in Child.__routes__

    def test_empty_subclass_has_empty_routes(self) -> None:
        """このdecorated methodを持たないsubclassの__routes__が空になることを検証する.

        plain methodだけを持つsubclassを定義し__routes__が空mappingと一致することを確認する.

        Returns:
            None: empty route集合の検証を完了する.
        """

        class EmptyGroup(RouteGroup):
            """route decoratorを持たないempty route検証用group."""

            async def plain_method(self) -> None:
                """このroute decoratorを持たないplain async method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        assert EmptyGroup.__routes__ == {}


class TestGetRoutes:
    """get_routesがroute keyとbound methodを返すことを検証するtest群."""

    def test_get_routes_returns_iterator(self) -> None:
        """get_routesがkeyとbound methodの組を返すことを検証する.

        the_keyのrouteを持つinstanceでget_routesをlist化し一件目のkeyがthe_keyになることを確認する.

        Returns:
            None: route iterator内容の検証を完了する.
        """

        class MyGroup(RouteGroup):
            """the_keyのrouteを持つiterator検証用group."""

            @route("the_key")
            async def the_handler(self) -> None:
                """the_keyに対応するiterator検証用method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        instance = MyGroup()
        routes = list(instance.get_routes())
        assert len(routes) == 1
        key, _bound_method = routes[0]
        assert key == "the_key"

    def test_get_routes_returns_bound_methods(self) -> None:
        """get_routesがinstanceへboundされたmethodを返すことを検証する.

        bound_checkのrouteを持つinstanceからmethodを取得しMethodTypeかつ__self__がそのinstanceであることを確認する.

        Returns:
            None: bound method返却の検証を完了する.
        """

        class MyGroup(RouteGroup):
            """bound_checkのrouteを持つbound method検証用group."""

            @route("bound_check")
            async def handler(self) -> None:
                """取得したbound methodとして検証するhandler.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        instance = MyGroup()
        routes = list(instance.get_routes())
        _, method = routes[0]
        # A bound method's __self__ should reference the instance
        assert isinstance(method, types.MethodType)
        assert method.__self__ is instance

    def test_get_routes_multiple(self) -> None:
        """get_routesが登録済みの全routeを返すことを検証する.

        alphaとbetaのrouteを持つinstanceからroute mappingを作り二keyがともに存在することを確認する.

        Returns:
            None: 複数route返却の検証を完了する.
        """

        class MyGroup(RouteGroup):
            """alphaとbetaのrouteを持つ複数取得検証用group."""

            @route("alpha")
            async def handle_alpha(self) -> None:
                """複数取得のalpha routeに対応する検証用method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

            @route("beta")
            async def handle_beta(self) -> None:
                """複数取得のbeta routeに対応する検証用method.

                Returns:
                    None: 副作用を持たずに完了する.
                """

        instance = MyGroup()
        routes = dict(instance.get_routes())
        expected_count = 2
        assert len(routes) == expected_count
        assert "alpha" in routes
        assert "beta" in routes

    def test_get_routes_methods_are_callable(self) -> None:
        """get_routesから得たmethodがcallableであることを検証する.

        call_checkのrouteを持つinstanceからroute mappingを作り対応methodへcallableを適用してTrueを
        確認する.

        Returns:
            None: callable route methodの検証を完了する.
        """

        class MyGroup(RouteGroup):
            """call_checkのrouteを持つcallable検証用group."""

            def __init__(self) -> None:
                """呼出し状態をFalseで初期化する."""
                self.called: bool = False

            @route("call_check")
            async def handler(self) -> None:
                """callableとして取得する検証用handler.

                Returns:
                    None: called状態を変更せずに完了する.
                """
                self.called = True

        instance = MyGroup()
        routes = dict(instance.get_routes())
        # Verify it's callable
        assert callable(routes["call_check"])

    async def test_get_routes_method_execution(self) -> None:
        """get_routesから得たbound methodをawaitして実行できることを検証する.

        exec_checkのrouteを持つinstanceからmethodを取得してawaitしcalled状態がTrueへ変わることを確認する.

        Returns:
            None: bound method実行の検証を完了する.
        """

        class MyGroup(RouteGroup):
            """exec_checkのrouteを持つ実行検証用group."""

            def __init__(self) -> None:
                """呼出し状態をFalseで初期化する."""
                self.called: bool = False

            @route("exec_check")
            async def handler(self) -> None:
                """await時にcalled状態を更新する実行検証用handler.

                Returns:
                    None: called状態をTrueへ更新して完了する.
                """
                self.called = True

        instance = MyGroup()
        routes = dict(instance.get_routes())
        await routes["exec_check"]()
        assert instance.called is True

    def test_get_routes_empty_group(self) -> None:
        """routeを持たないgroupのget_routesが空列を返すことを検証する.

        空groupを生成してget_routesをlist化し空listと一致することを確認する.

        Returns:
            None: empty route取得の検証を完了する.
        """

        class EmptyGroup(RouteGroup):
            """routeを持たないempty route取得検証用group."""

        instance = EmptyGroup()
        assert list(instance.get_routes()) == []


class TestConstructorDI:
    """RouteGroup subclassへのconstructor dependency injectionを検証するtest群."""

    def test_subclass_with_custom_init(self) -> None:
        """RouteGroup subclassが任意のconstructor dependencyを保持できることを検証する.

        strとintのdependencyを持つsubclassを生成し二fieldが渡した値と一致することを確認する.

        Returns:
            None: custom constructor dependency保持の検証を完了する.
        """

        class MyGroup(RouteGroup):
            """strとintのdependencyを保持するconstructor DI検証用group."""

            def __init__(self, dep_a: str, dep_b: int) -> None:
                """二つのdependencyをinstance fieldへ保存する.

                Args:
                    dep_a (str): 保存する文字列dependency.
                    dep_b (int): 保存する整数dependency.
                """
                self.dep_a: str = dep_a
                self.dep_b: int = dep_b

            @route("with_deps")
            async def handler(self) -> None:
                """dependencyを持つgroupへrouteを登録するhandler.

                Returns:
                    None: dependencyを変更せずに完了する.
                """

        dep_b_value = 42
        instance = MyGroup("hello", dep_b_value)
        assert instance.dep_a == "hello"
        assert instance.dep_b == dep_b_value

    async def test_handler_can_access_injected_deps(self) -> None:
        """このroute handlerがconstructorで注入したdependencyへアクセスできることを検証する.

        list sinkを持つgroupからdep_access handlerを取得してawaitしsinkにinvokedが追加されることを
        確認する.

        Returns:
            None: injected dependency利用の検証を完了する.
        """
        results: list[str] = []

        class MyGroup(RouteGroup):
            """list sinkを保持するdependency access検証用group."""

            def __init__(self, sink: list[str]) -> None:
                """handlerが利用するlist sinkを保存する.

                Args:
                    sink (list[str]): handler実行結果を追加する可変list.
                """
                self.sink: list[str] = sink

            @route("dep_access")
            async def handler(self) -> None:
                """注入済みsinkへ実行結果を追加するhandler.

                Returns:
                    None: sinkへinvokedを追加して完了する.
                """
                self.sink.append("invoked")

        instance = MyGroup(results)
        routes = dict(instance.get_routes())
        await routes["dep_access"]()
        assert results == ["invoked"]
