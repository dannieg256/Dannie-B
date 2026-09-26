from dataclasses import dataclass, asdict
from typing import Optional
import math


# ============================================================
# CANDIDATE MODEL
# ============================================================

@dataclass
class Candidate:
    ticker: str
    title: str

    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    midpoint: Optional[float] = None

    estimated_probability: Optional[float] = None
    edge: Optional[float] = None

    volume: float = 0.0
    volume_24h: float = 0.0
    open_interest: float = 0.0

    bid_size: Optional[float] = None
    ask_size: Optional[float] = None

    spread: Optional[float] = None
    quality_score: float = 0.0

    max_order_dollars: float = 0.0
    passed: bool = False
    notes: str = ""

    def dict(self):
        return asdict(self)


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(value, default=None):
    if value is None or value == "":
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_float(market, fields, default=None):
    for field in fields:
        value = market.get(field)

        if value is None or value == "":
            continue

        try:
            return float(value)
        except (TypeError, ValueError):
            continue

    return default


# ============================================================
# PRICE HELPERS
# ============================================================

def _dollar_price(value):
    value = _safe_float(value)

    if value is None:
        return None

    if value < 0:
        return None

    return value


def _cent_price(value):
    value = _safe_float(value)

    if value is None:
        return None

    if value < 0:
        return None

    return value / 100.0


def _get_price(
    market,
    dollar_field,
    legacy_field,
):
    value = market.get(
        dollar_field
    )

    if value is not None and value != "":
        return _dollar_price(
            value
        )

    value = market.get(
        legacy_field
    )

    if value is not None and value != "":
        return _cent_price(
            value
        )

    return None


def _valid_price(price):
    if price is None:
        return False

    try:
        price = float(price)
    except (TypeError, ValueError):
        return False

    return 0.0 < price < 1.0


# ============================================================
# ACTIVITY HELPERS
# ============================================================

def _get_volume(market):
    return _first_float(
        market,
        [
            "volume_fp",
            "volume",
        ],
        0.0,
    )


def _get_volume_24h(market):
    return _first_float(
        market,
        [
            "volume_24h_fp",
            "volume_24h",
        ],
        0.0,
    )


def _get_open_interest(market):
    return _first_float(
        market,
        [
            "open_interest_fp",
            "open_interest",
        ],
        0.0,
    )


def _get_bid_size(market):
    return _first_float(
        market,
        [
            "yes_bid_size_fp",
            "yes_bid_size",
            "bid_size_fp",
            "bid_size",
        ],
        None,
    )


def _get_ask_size(market):
    return _first_float(
        market,
        [
            "yes_ask_size_fp",
            "yes_ask_size",
            "ask_size_fp",
            "ask_size",
        ],
        None,
    )


# ============================================================
# QUALITY SCORE
# ============================================================

def _log_score(value, target):
    """
    Turns activity into a 0-1 score.

    Large values get diminishing returns.
    """

    value = max(
        0.0,
        float(value or 0)
    )

    if value <= 0:
        return 0.0

    return min(
        1.0,
        math.log1p(value)
        / math.log1p(target)
    )


def _spread_score(spread):
    """
    Smaller spreads receive higher scores.
    """

    if spread is None:
        return 0.0

    spread = max(
        0.0,
        float(spread)
    )

    if spread <= 0.01:
        return 1.00

    if spread <= 0.03:
        return 0.90

    if spread <= 0.05:
        return 0.75

    if spread <= 0.10:
        return 0.50

    if spread <= 0.15:
        return 0.25

    return 0.0


def _calculate_quality(
    bid,
    ask,
    volume,
    volume_24h,
    open_interest,
    bid_size,
    ask_size,
):
    if (
        not _valid_price(bid)
        or not _valid_price(ask)
    ):
        return 0.0

    if bid > ask:
        return 0.0

    spread = ask - bid

    spread_component = (
        _spread_score(spread)
    )

    volume_component = _log_score(
        max(
            volume,
            volume_24h,
        ),
        1000,
    )

    open_interest_component = (
        _log_score(
            open_interest,
            1000,
        )
    )

    depth_value = 0.0

    if (
        bid_size is not None
        and ask_size is not None
    ):
        depth_value = min(
            max(0.0, bid_size),
            max(0.0, ask_size),
        )

    depth_component = _log_score(
        depth_value,
        100,
    )

    # 0-100 score
    score = (
        spread_component * 45
        + volume_component * 25
        + open_interest_component * 20
        + depth_component * 10
    )

    return round(
        max(
            0.0,
            min(
                100.0,
                score,
            ),
        ),
        1,
    )


# ============================================================
# 1. MARKET SCANNER AGENT
# ============================================================

class MarketScannerAgent:
    name = "1. Market Scanner"

    def run(
        self,
        markets,
        min_volume=0,
    ):
        candidates = []

        for market in markets:

            if not isinstance(
                market,
                dict,
            ):
                continue

            ticker = market.get(
                "ticker"
            )

            if not ticker:
                continue

            bid = _get_price(
                market,
                "yes_bid_dollars",
                "yes_bid",
            )

            ask = _get_price(
                market,
                "yes_ask_dollars",
                "yes_ask",
            )

            if (
                not _valid_price(bid)
                or not _valid_price(ask)
            ):
                continue

            if bid > ask:
                continue

            volume = _get_volume(
                market
            )

            volume_24h = (
                _get_volume_24h(
                    market
                )
            )

            activity = max(
                volume,
                volume_24h,
            )

            if activity < float(
                min_volume
            ):
                continue

            open_interest = (
                _get_open_interest(
                    market
                )
            )

            bid_size = _get_bid_size(
                market
            )

            ask_size = _get_ask_size(
                market
            )

            quality = _calculate_quality(
                bid,
                ask,
                volume,
                volume_24h,
                open_interest,
                bid_size,
                ask_size,
            )

            # Store these values so later agents
            # do not have to calculate them again.
            market[
                "_quality_score"
            ] = quality

            market[
                "_volume_24h"
            ] = volume_24h

            market[
                "_open_interest"
            ] = open_interest

            market[
                "_bid_size"
            ] = bid_size

            market[
                "_ask_size"
            ] = ask_size

            candidates.append(
                market
            )

        # Best overall market quality first.
        candidates.sort(
            key=lambda market: (
                market.get(
                    "_quality_score",
                    0,
                ),
                _get_volume_24h(
                    market
                ),
                _get_volume(
                    market
                ),
            ),
            reverse=True,
        )

        return candidates


# ============================================================
# 2. RULES AGENT
# ============================================================

class RulesAgent:
    name = "2. Rules Agent"

    def run(
        self,
        market,
    ):
        primary_rules = (
            market.get(
                "rules_primary"
            )
            or market.get(
                "rules"
            )
            or ""
        )

        secondary_rules = (
            market.get(
                "rules_secondary"
            )
            or ""
        )

        subtitle = (
            market.get(
                "subtitle"
            )
            or ""
        )

        return {
            "close_time": market.get(
                "close_time"
            ),
            "expiration_time": market.get(
                "expiration_time"
            ),
            "rules": primary_rules,
            "secondary_rules": secondary_rules,
            "subtitle": subtitle,
        }


# ============================================================
# 3. DATA AGENT
# ============================================================

class DataAgent:
    name = "3. Data Agent"

    def run(
        self,
        market,
    ):
        yes_bid = _get_price(
            market,
            "yes_bid_dollars",
            "yes_bid",
        )

        yes_ask = _get_price(
            market,
            "yes_ask_dollars",
            "yes_ask",
        )

        no_bid = _get_price(
            market,
            "no_bid_dollars",
            "no_bid",
        )

        no_ask = _get_price(
            market,
            "no_ask_dollars",
            "no_ask",
        )

        last_price = _get_price(
            market,
            "last_price_dollars",
            "last_price",
        )

        volume = _get_volume(
            market
        )

        volume_24h = (
            _get_volume_24h(
                market
            )
        )

        open_interest = (
            _get_open_interest(
                market
            )
        )

        bid_size = _get_bid_size(
            market
        )

        ask_size = _get_ask_size(
            market
        )

        midpoint = None
        spread = None

        if (
            _valid_price(yes_bid)
            and _valid_price(yes_ask)
        ):
            midpoint = (
                yes_bid
                + yes_ask
            ) / 2.0

            spread = (
                yes_ask
                - yes_bid
            )

        elif _valid_price(
            last_price
        ):
            midpoint = (
                last_price
            )

        quality_score = (
            market.get(
                "_quality_score"
            )
        )

        if quality_score is None:
            quality_score = (
                _calculate_quality(
                    yes_bid,
                    yes_ask,
                    volume,
                    volume_24h,
                    open_interest,
                    bid_size,
                    ask_size,
                )
            )

        return {
            "ticker": market.get(
                "ticker"
            ),
            "title": market.get(
                "title"
            ),
            "subtitle": market.get(
                "subtitle"
            ),

            "yes_bid": yes_bid,
            "yes_ask": yes_ask,

            "no_bid": no_bid,
            "no_ask": no_ask,

            "last_price": last_price,
            "midpoint": midpoint,
            "spread": spread,

            "volume": volume,
            "volume_24h": volume_24h,
            "open_interest": open_interest,

            "bid_size": bid_size,
            "ask_size": ask_size,

            "quality_score": (
                quality_score
            ),
        }


# ============================================================
# 4. PROBABILITY AGENT
# ============================================================

class ProbabilityAgent:
    name = "4. Probability Agent"

    def run(
        self,
        data,
        user_probability=None,
    ):
        # User estimate takes priority.
        if user_probability is not None:

            probability = float(
                user_probability
            )

            probability = max(
                0.01,
                min(
                    0.99,
                    probability,
                ),
            )

            return (
                probability,
                "user supplied probability",
            )

        bid = data.get(
            "yes_bid"
        )

        ask = data.get(
            "yes_ask"
        )

        last_price = data.get(
            "last_price"
        )

        if (
            _valid_price(bid)
            and _valid_price(ask)
        ):
            midpoint = (
                bid + ask
            ) / 2.0

            # If a real last trade exists,
            # lightly blend it with midpoint.
            if _valid_price(
                last_price
            ):
                probability = (
                    midpoint * 0.75
                    + last_price * 0.25
                )

                return (
                    probability,
                    "market midpoint + last trade baseline",
                )

            return (
                midpoint,
                "market midpoint baseline",
            )

        if _valid_price(
            last_price
        ):
            return (
                last_price,
                "last trade baseline",
            )

        if _valid_price(
            bid
        ):
            return (
                bid,
                "YES bid baseline",
            )

        if _valid_price(
            ask
        ):
            return (
                ask,
                "YES ask baseline",
            )

        return (
            0.50,
            "neutral fallback",
        )


# ============================================================
# 5. VALUE AGENT
# ============================================================

class ValueAgent:
    name = "5. Value Agent"

    def run(
        self,
        probability,
        yes_ask,
    ):
        if probability is None:
            return None

        if not _valid_price(
            yes_ask
        ):
            return None

        try:
            probability = float(
                probability
            )

            yes_ask = float(
                yes_ask
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        return (
            probability
            - yes_ask
        )


# ============================================================
# 6. LIQUIDITY AGENT
# ============================================================

class LiquidityAgent:
    name = "6. Liquidity Agent"

    def run(
        self,
        data,
        max_spread,
    ):
        bid = data.get(
            "yes_bid"
        )

        ask = data.get(
            "yes_ask"
        )

        if not _valid_price(
            bid
        ):
            return {
                "passed": False,
                "spread": None,
                "reason": "No usable YES bid.",
            }

        if not _valid_price(
            ask
        ):
            return {
                "passed": False,
                "spread": None,
                "reason": "No usable YES ask.",
            }

        spread = (
            ask - bid
        )

        if spread < 0:
            return {
                "passed": False,
                "spread": spread,
                "reason": "Invalid inverted market.",
            }

        if spread > float(
            max_spread
        ):
            return {
                "passed": False,
                "spread": spread,
                "reason": (
                    f"spread {spread * 100:.1f}¢ "
                    f"exceeds limit "
                    f"{float(max_spread) * 100:.1f}¢"
                ),
            }

        bid_size = data.get(
            "bid_size"
        )

        ask_size = data.get(
            "ask_size"
        )

        # Only enforce depth when both size
        # fields are actually supplied.
        if (
            bid_size is not None
            and ask_size is not None
        ):
            try:
                bid_size = float(
                    bid_size
                )

                ask_size = float(
                    ask_size
                )

                if (
                    bid_size <= 0
                    or ask_size <= 0
                ):
                    return {
                        "passed": False,
                        "spread": spread,
                        "reason": (
                            "No displayed depth "
                            "on both sides."
                        ),
                    }

            except (
                TypeError,
                ValueError,
            ):
                pass

        return {
            "passed": True,
            "spread": spread,
            "reason": "ok",
        }


# ============================================================
# 7. RISK AGENT
# ============================================================

class RiskAgent:
    name = "7. Risk Agent"

    def __init__(
        self,
        max_order_dollars,
        max_daily_dollars,
        max_open_exposure_dollars,
        min_edge,
    ):
        self.max_order = float(
            max_order_dollars
        )

        self.max_daily = float(
            max_daily_dollars
        )

        self.max_exposure = float(
            max_open_exposure_dollars
        )

        self.min_edge = float(
            min_edge
        )

    def evaluate(
        self,
        edge,
        proposed_dollars,
        daily_spent=0.0,
        open_exposure=0.0,
    ):
        problems = []

        proposed_dollars = float(
            proposed_dollars
        )

        daily_spent = float(
            daily_spent
        )

        open_exposure = float(
            open_exposure
        )

        if proposed_dollars <= 0:
            problems.append(
                "order amount must be positive"
            )

        if edge is None:
            problems.append(
                "unable to calculate edge"
            )

        elif edge < self.min_edge:
            problems.append(
                f"edge below {self.min_edge:.1%}"
            )

        if (
            proposed_dollars
            > self.max_order
        ):
            problems.append(
                "order exceeds max order limit"
            )

        if (
            daily_spent
            + proposed_dollars
            > self.max_daily
        ):
            problems.append(
                "daily spend limit exceeded"
            )

        if (
            open_exposure
            + proposed_dollars
            > self.max_exposure
        ):
            problems.append(
                "open exposure limit exceeded"
            )

        return {
            "passed": not problems,
            "problems": problems,
        }


# ============================================================
# 8. PORTFOLIO AGENT
# ============================================================

class PortfolioAgent:
    name = "8. Portfolio Agent"

    def run(
        self,
        client,
    ):
        try:
            balance = (
                client.get_balance()
            )

        except Exception as e:
            balance = {
                "error": str(e)
            }

        try:
            positions = (
                client.get_positions()
            )

        except Exception as e:
            positions = {
                "error": str(e)
            }

        return {
            "balance": balance,
            "positions": positions,
        }


# ============================================================
# 9. EXECUTION AGENT
# ============================================================

class ExecutionAgent:
    name = "9. Execution Agent"

    def prepare(
        self,
        ticker,
        price,
        dollars,
    ):
        price = float(
            price
        )

        dollars = float(
            dollars
        )

        if not (
            0.01
            <= price
            <= 0.99
        ):
            raise ValueError(
                "Price must be between $0.01 and $0.99."
            )

        if dollars <= 0:
            raise ValueError(
                "Dollar amount must be positive."
            )

        count = math.floor(
            dollars / price
        )

        if count < 1:
            raise ValueError(
                "Order amount is too small "
                "for one contract."
            )

        actual_cost = (
            count * price
        )

        # Never exceed the requested budget.
        while (
            count > 0
            and actual_cost
            > dollars
        ):
            count -= 1

            actual_cost = (
                count * price
            )

        if count < 1:
            raise ValueError(
                "Order amount is too small."
            )

        return {
            "ticker": ticker,
            "price": round(
                price,
                4,
            ),
            "count": count,
            "estimated_cost": round(
                actual_cost,
                2,
            ),
        }
