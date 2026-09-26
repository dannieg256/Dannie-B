from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
import math


@dataclass
class Candidate:
    ticker: str
    title: str
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    midpoint: Optional[float] = None
    estimated_probability: Optional[float] = None
    edge: Optional[float] = None
    volume: float = 0
    spread: Optional[float] = None
    max_order_dollars: float = 0
    passed: bool = False
    notes: str = ""

    def dict(self):
        return asdict(self)


def _money_to_float(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
        # Some legacy fields are cents; dollar fixed-point fields are already <= 1.
        return x / 100.0 if x > 1.0 else x
    except Exception:
        return None


class MarketScannerAgent:
    name = "1. Market Scanner"

    def run(self, markets, min_volume=0):
        out = []
        for m in markets:
            volume = float(m.get("volume") or m.get("volume_fp") or 0)
            if volume < min_volume:
                continue
            out.append(m)
        return out


class RulesAgent:
    name = "2. Rules Agent"

    def run(self, market):
        # Prefer explicit rule fields if supplied by API.
        rule_text = (
            market.get("rules_primary")
            or market.get("rules")
            or market.get("subtitle")
            or ""
        )
        return {
            "close_time": market.get("close_time"),
            "expiration_time": market.get("expiration_time"),
            "rules": rule_text,
        }


class DataAgent:
    name = "3. Data Agent"

    def run(self, market):
        # Extend this later with sports/weather/economic APIs.
        return {
            "ticker": market.get("ticker"),
            "title": market.get("title"),
            "volume": float(market.get("volume") or market.get("volume_fp") or 0),
            "yes_bid": _money_to_float(market.get("yes_bid_dollars") or market.get("yes_bid")),
            "yes_ask": _money_to_float(market.get("yes_ask_dollars") or market.get("yes_ask")),
        }


class ProbabilityAgent:
    name = "4. Probability Agent"

    def run(self, data, user_probability=None):
        if user_probability is not None:
            p = max(0.01, min(0.99, float(user_probability)))
            return p, "user supplied probability"

        bid, ask = data.get("yes_bid"), data.get("yes_ask")
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0, "market-midpoint baseline (no external model)"
        if bid is not None:
            return bid, "yes-bid baseline"
        if ask is not None:
            return ask, "yes-ask baseline"
        return 0.50, "neutral fallback"


class ValueAgent:
    name = "5. Value Agent"

    def run(self, probability, yes_ask):
        if yes_ask is None:
            return None
        return probability - yes_ask


class LiquidityAgent:
    name = "6. Liquidity Agent"

    def run(self, data, max_spread):
        bid, ask = data.get("yes_bid"), data.get("yes_ask")
        if bid is None or ask is None:
            return {"passed": False, "spread": None, "reason": "Missing bid/ask"}
        spread = max(0.0, ask - bid)
        return {
            "passed": spread <= max_spread,
            "spread": spread,
            "reason": "ok" if spread <= max_spread else "spread too wide",
        }


class RiskAgent:
    name = "7. Risk Agent"

    def __init__(self, max_order_dollars, max_daily_dollars, max_open_exposure_dollars, min_edge):
        self.max_order = max_order_dollars
        self.max_daily = max_daily_dollars
        self.max_exposure = max_open_exposure_dollars
        self.min_edge = min_edge

    def evaluate(self, edge, proposed_dollars, daily_spent=0.0, open_exposure=0.0):
        problems = []
        if edge is None or edge < self.min_edge:
            problems.append(f"edge below {self.min_edge:.1%}")
        if proposed_dollars > self.max_order:
            problems.append("order exceeds max order limit")
        if daily_spent + proposed_dollars > self.max_daily:
            problems.append("daily spend limit exceeded")
        if open_exposure + proposed_dollars > self.max_exposure:
            problems.append("open exposure limit exceeded")
        return {"passed": not problems, "problems": problems}


class PortfolioAgent:
    name = "8. Portfolio Agent"

    def run(self, client):
        try:
            balance = client.get_balance()
        except Exception as e:
            balance = {"error": str(e)}
        try:
            positions = client.get_positions()
        except Exception as e:
            positions = {"error": str(e)}
        return {"balance": balance, "positions": positions}


class ExecutionAgent:
    name = "9. Execution Agent"

    def prepare(self, ticker, price, dollars):
        price = float(price)
        dollars = float(dollars)
        if not (0.01 <= price <= 0.99):
            raise ValueError("Price must be between $0.01 and $0.99.")
        if dollars <= 0:
            raise ValueError("Dollar amount must be positive.")
        count = max(1, math.floor(dollars / price))
        actual_cost = count * price
        return {
            "ticker": ticker,
            "price": round(price, 4),
            "count": count,
            "estimated_cost": round(actual_cost, 2),
        }
