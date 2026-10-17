"""Shared, transport-neutral strategy contracts.

Keep strategy result and protocol separate from strategy implementations so
candidate plugins do not import the registry or create circular imports.
"""
from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class ScreenResult:
    market: str
    symbol: str
    strategy_id: str
    strategy_version: str
    trade_date: str
    matched: bool
    metrics: dict
    reason: str


class ScreeningStrategy(Protocol):
    id: str
    version: str

    def scan(self, market: str, symbol: str, data: pd.DataFrame,
             params: dict) -> ScreenResult: ...
