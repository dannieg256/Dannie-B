import os
import uuid
import secrets
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from kalshi_client import KalshiClient
from agents import (
    MarketScannerAgent,
    RulesAgent,
    DataAgent,
    ProbabilityAgent,
    ValueAgent,
    LiquidityAgent,
    RiskAgent,
    PortfolioAgent,
    ExecutionAgent,
)


# ============================================================
# BUILD
# ============================================================

APP_BUILD = "quality-dashboard-v4"


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

ENV = os.getenv("KALSHI_ENV", "demo").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "")

PRIVATE_KEY_PATH = os.getenv(
    "KALSHI_PRIVATE_KEY_PATH",
    "./kalshi-private-key.pem",
)

MAX_ORDER = float(
    os.getenv("MAX_ORDER_DOLLARS", "10")
)

MAX_DAILY = float(
    os.getenv("MAX_DAILY_DOLLARS", "30")
)

MAX_EXPOSURE = float(
    os.getenv("MAX_OPEN_EXPOSURE_DOLLARS", "50")
)

MIN_EDGE = (
    float(os.getenv("MIN_EDGE_PERCENT", "5"))
    / 100.0
)

MIN_VOLUME = float(
    os.getenv("MIN_VOLUME", "0")
)

MAX_SPREAD = (
    float(os.getenv("MAX_SPREAD_CENTS", "15"))
    / 100.0
)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Kalshi 9-Agent Dashboard"
)

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


# ============================================================
# CLIENTS
# ============================================================

client = KalshiClient(
    API_KEY_ID,
    PRIVATE_KEY_PATH,
    ENV,
)

market_client = KalshiClient(
    "",
    "",
    "production",
)


# ============================================================
# AGENTS
# ============================================================

scanner = MarketScannerAgent()
rules_agent = RulesAgent()
data_agent = DataAgent()
prob_agent = ProbabilityAgent()
value_agent = ValueAgent()
liq_agent = LiquidityAgent()

risk_agent = RiskAgent(
    MAX_ORDER,
    MAX_DAILY,
    MAX_EXPOSURE,
    MIN_EDGE,
)

portfolio_agent = PortfolioAgent()
execution_agent = ExecutionAgent()


# ============================================================
# TEMPORARY STORAGE
# ============================================================

pending_orders = {}
paper_log = []
daily_spent = 0.0


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "build": APP_BUILD,
        "environment": ENV,
        "live_trading": LIVE_TRADING,
        "max_order": MAX_ORDER,
        "max_daily": MAX_DAILY,
        "max_exposure": MAX_EXPOSURE,
        "min_edge_percent": MIN_EDGE * 100,
        "min_volume": MIN_VOLUME,
        "max_spread": MAX_SPREAD,
        "max_spread_cents": MAX_SPREAD * 100,
    }


# ============================================================
# MARKET FILTER
# ============================================================

def eligible_market(market):
    data = data_agent.run(market)

    bid = data.get("yes_bid")
    ask = data.get("yes_ask")
    volume = data.get("volume", 0)

    if bid is None or ask is None:
        return None

    try:
        bid = float(bid)
        ask = float(ask)
        volume = float(volume or 0)
    except (TypeError, ValueError):
        return None

    # Valid contract prices only.
    if not 0 < bid < 1:
        return None

    if not 0 < ask < 1:
        return None

    if bid > ask:
        return None

    spread = ask - bid

    # HARD FILTER:
    # A market wider than the configured spread
    # never reaches the homepage.
    if spread > MAX_SPREAD:
        return None

    if volume < MIN_VOLUME:
        return None

    # Run the same liquidity agent used
    # on the market detail page.
    liquidity = liq_agent.run(
        data,
        MAX_SPREAD,
    )

    if not liquidity.get("passed", False):
        return None

    return {
        "ticker": market.get("ticker"),
        "title": market.get("title"),
        "volume": volume,
        "yes_bid": bid,
        "yes_ask": ask,
        "midpoint": (bid + ask) / 2.0,
        "spread": spread,
        "close_time": market.get("close_time"),
    }


# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
def home(request: Request):

    error = None
    markets = []

    try:
        response = market_client.get_markets(
            limit=100,
            status="open",
        )

        raw_markets = response.get(
            "markets",
            [],
        )

        scanned_markets = scanner.run(
            raw_markets,
            MIN_VOLUME,
        )

        for market in scanned_markets:

            item = eligible_market(
                market
            )

            if item is None:
                continue

            markets.append(
                item
            )

        # Tightest spreads first,
        # then highest volume.
        markets.sort(
            key=lambda item: (
                item.get("spread", 999),
                -item.get("volume", 0),
            )
        )

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "env": ENV,
            "live": LIVE_TRADING,
            "markets": markets[:50],
            "error": error,
            "limits": {
                "max_order": MAX_ORDER,
                "max_daily": MAX_DAILY,
                "max_exposure": MAX_EXPOSURE,
                "min_edge": MIN_EDGE * 100,
                "max_spread": MAX_SPREAD * 100,
            },
            "paper_log": list(
                reversed(
                    paper_log[-10:]
                )
            ),
        },
        headers={
            "Cache-Control": (
                "no-store, no-cache, "
                "must-revalidate, max-age=0"
            ),
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# ============================================================
# MARKET PAGE
# ============================================================

@app.get(
    "/market/{ticker}",
    response_class=HTMLResponse,
)
def market_page(
    request: Request,
    ticker: str,
    p: Optional[float] = None,
):

    try:
        response = market_client.get_market(
            ticker
        )

        market = response.get(
            "market",
            {},
        )

        if not market:
            raise HTTPException(
                status_code=404,
                detail="Market not found.",
            )

        data = data_agent.run(
            market
        )

        rules = rules_agent.run(
            market
        )

        probability, prob_source = (
            prob_agent.run(
                data,
                p,
            )
        )

        edge = value_agent.run(
            probability,
            data.get("yes_ask"),
        )

        liquidity = liq_agent.run(
            data,
            MAX_SPREAD,
        )

        return templates.TemplateResponse(
            "market.html",
            {
                "request": request,
                "env": ENV,
                "live": LIVE_TRADING,
                "market": market,
                "data": data,
                "rules": rules,
                "probability": probability,
                "prob_source": prob_source,
                "edge": edge,
                "liquidity": liquidity,
                "max_order": MAX_ORDER,
                "min_edge": MIN_EDGE,
            },
            headers={
                "Cache-Control": "no-store"
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# ============================================================
# PREPARE ORDER
# ============================================================

@app.post("/prepare/{ticker}")
def prepare_order(
    ticker: str,
    probability_percent: float = Form(...),
    dollars: float = Form(...),
):

    try:
        response = market_client.get_market(
            ticker
        )

        market = response.get(
            "market",
            {},
        )

        if not market:
            raise HTTPException(
                status_code=404,
                detail="Market not found.",
            )

        data = data_agent.run(
            market
        )

        bid = data.get(
            "yes_bid"
        )

        ask = data.get(
            "yes_ask"
        )

        if bid is None or ask is None:
            raise HTTPException(
                status_code=400,
                detail="Market is missing a usable bid or ask.",
            )

        bid = float(bid)
        ask = float(ask)

        if not 0.01 <= ask <= 0.99:
            raise HTTPException(
                status_code=400,
                detail="Invalid YES ask price.",
            )

        spread = ask - bid

        # Recheck spread at order time.
        if spread > MAX_SPREAD:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Spread is {spread * 100:.1f}¢. "
                    f"Maximum allowed is "
                    f"{MAX_SPREAD * 100:.1f}¢."
                ),
            )

        liquidity = liq_agent.run(
            data,
            MAX_SPREAD,
        )

        if not liquidity.get(
            "passed",
            False,
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Liquidity check failed: "
                    + str(
                        liquidity.get(
                            "reason",
                            "Unknown reason",
                        )
                    )
                ),
            )

        probability, _ = prob_agent.run(
            data,
            probability_percent / 100.0,
        )

        edge = value_agent.run(
            probability,
            ask,
        )

        dollars = float(
            dollars
        )

        dollars = max(
            0.0,
            min(
                dollars,
                MAX_ORDER,
            ),
        )

        if dollars <= 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Order amount must be greater than $0."
                ),
            )

        risk = risk_agent.evaluate(
            edge,
            dollars,
            daily_spent=daily_spent,
            open_exposure=0.0,
        )

        if not risk.get(
            "passed",
            False,
        ):
            problems = risk.get(
                "problems",
                [],
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Risk check failed: "
                    + "; ".join(problems)
                ),
            )

        order = execution_agent.prepare(
            ticker,
            ask,
            dollars,
        )

        token = secrets.token_urlsafe(
            24
        )

        pending_orders[token] = {
            **order,
            "title": market.get("title"),
            "estimated_probability": probability,
            "edge": edge,
            "spread": spread,
        }

        return RedirectResponse(
            url=f"/approve/{token}",
            status_code=303,
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# ============================================================
# APPROVAL
# ============================================================

@app.get(
    "/approve/{token}",
    response_class=HTMLResponse,
)
def approve_page(
    request: Request,
    token: str,
):

    order = pending_orders.get(
        token
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail=(
                "Approval request expired "
                "or not found."
            ),
        )

    return templates.TemplateResponse(
        "approve.html",
        {
            "request": request,
            "token": token,
            "order": order,
            "env": ENV,
            "live": LIVE_TRADING,
        },
        headers={
            "Cache-Control": "no-store"
        },
    )


# ============================================================
# EXECUTE
# ============================================================

@app.post("/execute/{token}")
def execute(token: str):

    global daily_spent

    order = pending_orders.pop(
        token,
        None,
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail=(
                "Approval request expired "
                "or already used."
            ),
        )

    client_order_id = str(
        uuid.uuid4()
    )

    estimated_cost = float(
        order.get(
            "estimated_cost",
            0,
        )
    )

    # PAPER MODE
    if not LIVE_TRADING:

        result = {
            "mode": "paper",
            "client_order_id": client_order_id,
            **order,
        }

        paper_log.append(
            result
        )

        daily_spent += estimated_cost

        return RedirectResponse(
            url="/?paper=1",
            status_code=303,
        )

    # LIVE TRADING MUST ALSO BE PRODUCTION.
    if ENV != "production":
        raise HTTPException(
            status_code=400,
            detail=(
                "LIVE_TRADING=true but "
                "KALSHI_ENV is not production. "
                "Refusing to submit."
            ),
        )

    try:
        result = client.create_order(
            order["ticker"],
            order["price"],
            order["count"],
            client_order_id,
        )

        daily_spent += estimated_cost

        paper_log.append(
            {
                "mode": "live",
                "response": result,
                **order,
            }
        )

        return RedirectResponse(
            url="/?live=1",
            status_code=303,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Order submission failed: "
                + str(e)
            ),
        )


# ============================================================
# PORTFOLIO
# ============================================================

@app.get(
    "/portfolio",
    response_class=HTMLResponse,
)
def portfolio(
    request: Request
):

    try:
        result = portfolio_agent.run(
            client
        )

        return templates.TemplateResponse(
            "portfolio.html",
            {
                "request": request,
                "result": result,
                "env": ENV,
            },
            headers={
                "Cache-Control": "no-store"
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
