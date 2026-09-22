from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import requests


BSTOCK_LIST_URL = (
    "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/"
    "market/token/rwa/stock/detail/list/ai"
)
ASSET_STATUS_URL = (
    "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/"
    "market/token/rwa/asset/market/status/ai"
)
HEADERS = {"Accept-Encoding": "identity", "User-Agent": "binance-web3/1.1 (Skill)"}
EXCHANGE_SPOT_INFO_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"


@dataclass(frozen=True)
class BStockAsset:
    ticker: str
    symbol: str
    contract_address: str
    chain_id: str
    spot_symbol: str
    multiplier: str


@dataclass(frozen=True)
class BStockMarketStatus:
    open_state: bool
    reason_code: str | None
    reason_message: str | None
    market_status: str | None


class BStockCatalogClient:
    def __init__(self, *, session: Any | None = None, timeout: float = 10.0) -> None:
        self.session = session or requests
        self.timeout = timeout

    def list_assets(self) -> list[BStockAsset]:
        payload = self._get(BSTOCK_LIST_URL, {"type": 3})
        assets: list[BStockAsset] = []
        for row in payload.get("data") or []:
            if int(row.get("type", 0)) != 3 or str(row.get("chainId")) != "56":
                continue
            symbol = str(row.get("symbol", "")).upper()
            address = str(row.get("contractAddress", ""))
            if symbol and address:
                assets.append(BStockAsset(
                    ticker=str(row.get("ticker", "")).upper(),
                    symbol=symbol,
                    contract_address=address,
                    chain_id="56",
                    spot_symbol=str(row.get("cs") or f"{symbol}USDT").upper(),
                    multiplier=str(row.get("multiplier") or "1"),
                ))
        return assets

    def resolve(self, symbol_or_ticker: str) -> BStockAsset:
        candidate = symbol_or_ticker.strip().upper()
        for asset in self.list_assets():
            if candidate in {asset.symbol, asset.ticker, asset.spot_symbol}:
                return asset
        raise ValueError(f"Binance type=3 bStock 未找到：{candidate}")

    def market_status(self, asset: BStockAsset) -> BStockMarketStatus:
        payload = self._get(ASSET_STATUS_URL, {
            "chainId": asset.chain_id,
            "contractAddress": asset.contract_address,
        })
        data = payload.get("data") or {}
        return BStockMarketStatus(
            open_state=bool(data.get("openState")),
            reason_code=data.get("reasonCode"),
            reason_message=data.get("reasonMsg"),
            market_status=data.get("marketStatus"),
        )

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(url, params=params, headers=HEADERS, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success") or payload.get("code") != "000000":
            raise RuntimeError(f"Binance bStock API 返回失败：{payload}")
        return payload


class BinanceExchangeSpotCatalogClient:
    """Public Binance exchange Spot identity/status; never reads an account."""

    def __init__(self, *, session: Any | None = None, timeout: float = 10.0,
                 base_url: str = EXCHANGE_SPOT_INFO_URL) -> None:
        self.session = session or requests
        self.timeout = timeout
        self.base_url = base_url

    def resolve(self, symbol: str) -> BStockAsset:
        normalized = self._symbol(symbol)
        row = self._row(normalized)
        base, quote = row.get("baseAsset"), row.get("quoteAsset")
        if (not isinstance(base, str) or not isinstance(quote, str)
                or base + quote != normalized
                or row.get("isSpotTradingAllowed") is not True):
            raise ValueError("Invalid Binance exchange Spot instrument")
        return BStockAsset(base, base, "", "", normalized, "1")

    def market_status(self, asset: BStockAsset) -> BStockMarketStatus:
        if not isinstance(asset, BStockAsset):
            raise ValueError("Invalid Binance exchange Spot asset")
        row = self._row(self._symbol(asset.spot_symbol))
        status = row.get("status")
        allowed = row.get("isSpotTradingAllowed") is True
        trading = status == "TRADING" and allowed
        return BStockMarketStatus(
            trading, "TRADING" if trading else str(status or "UNKNOWN"),
            None if trading else "Binance exchange Spot market unavailable",
            str(status) if status is not None else None,
        )

    @staticmethod
    def _symbol(value: str) -> str:
        normalized = value.strip().upper() if isinstance(value, str) else ""
        if not re.fullmatch(r"[A-Z0-9]{5,32}", normalized):
            raise ValueError("Invalid Binance exchange Spot symbol")
        return normalized

    def _row(self, symbol: str) -> dict[str, Any]:
        response = self.session.get(
            self.base_url, params={"symbol": symbol}, headers=HEADERS,
            timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("symbols") if isinstance(payload, dict) else None
        if (not isinstance(rows, list) or len(rows) != 1
                or not isinstance(rows[0], dict)
                or rows[0].get("symbol") != symbol):
            raise ValueError("Binance exchange Spot symbol not found")
        return rows[0]

