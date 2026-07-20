"""Dishka provider decoratorへ型付きで接続するlocal facadeを提供する."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import dishka

type ProviderFactory = Callable[..., object]
type ProviderDecorator = Callable[[ProviderFactory], object]

provide = cast("ProviderDecorator", dishka.provide)
