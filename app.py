import os
import uuid
import secrets
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request

from kalshi_client import KalshiClient
from agents import (
    MarketScannerAgent, RulesAgent, DataAgent, ProbabilityAgent,
    ValueAgent, LiquidityAgent, RiskAgent, PortfolioAgent, ExecutionAgent
)

load_dotenv()

ENV = os.getenv("KALSHI_ENV", "demo").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "")
PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "./kalshi-private-key.pem")

MAX_ORDER = float(os.getenv("MAX_ORDER_DOLLARS", "10"))
MAX_DAILY = float(os.getenv("MAX_DAILY_DOLLARS", "30"))
MAX_EXPOSURE = float(os.getenv("MAX_OPEN_EXPOSURE_DOLLARS", "50"))
MIN_EDGE = float(os.getenv("MIN_EDGE_PERCENT", "5")) / 100
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "50"))
MAX_SPREAD = float(os.getenv("MAX_SPREAD_CENTS", "15")) / 100

app = FastAPI(title="Kalshi 9-Agent Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
client = KalshiClient(API_KEY_ID, PRIVATE_KEY_PATH, ENV)
market_client = KalshiClient("", "", "production")
scanner = MarketScannerAgent()
rules_agent = RulesAgent()
data_agent = DataAgent()
prob_agent = ProbabilityAgent()
value_agent = ValueAgent()
liq_agent = LiquidityAgent()
risk_agent = RiskAgent(MAX_ORDER, MAX_DAILY, MAX_EXPOSURE, MIN_EDGE)
portfolio_agent = PortfolioAgent()
execution_agent = ExecutionAgent()

pending_orders = {}
paper_log = []
daily_spent = 0.0


def fmt_market(m):
    data = data_agent.run(m)
    bid, ask = data["yes_bid"], data["yes_ask"]
    midpoint = ((bid + ask) / 2) if bid is not None and ask is not None else None
    return {
        "ticker": m.get("ticker"),
        "title": m.get("title"),
        "volume": data["volume"],
        "yes_bid": bid,
        "yes_ask": ask,
        "midpoint": midpoint,
        "close_time": m.get("close_time"),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    error = None
    markets = []
    try
    
        raw = market_client.get_markets(limit=100, status="open").get("markets", [])
        markets = [fmt_market(m) for m in scanner.run(raw, MIN_VOLUME)]
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse("index.html", {
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
        "paper_log": list(reversed(paper_log[-10:])),
    })


@app.get("/market/{ticker}", response_class=HTMLResponse)
def market_page(request: Request, ticker: str, p: Optional[float] = None):
    market = market_client.get_market(ticker).get("market", {})
    data = data_agent.run(market)
    rules = rules_agent.run(market)
    probability, prob_source = prob_agent.run(data, p)
    edge = value_agent.run(probability, data["yes_ask"])
    liquidity = liq_agent.run(data, MAX_SPREAD)

    return templates.TemplateResponse("market.html", {
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
    })


@app.post("/prepare/{ticker}")
def prepare_order(
    ticker: str,
    probability_percent: float = Form(...),
    dollars: float = Form(...),
):
    market = market_client.get_market(ticker).get("market", {})
    data = data_agent.run(market)

    probability, _ = prob_agent.run(data, probability_percent / 100.0)
    edge = value_agent.run(probability, data["yes_ask"])
    liquidity = liq_agent.run(data, MAX_SPREAD)

    if data["yes_ask"] is None:
        raise HTTPException(400, "No YES ask available.")

    # Proposed dollars are capped before preparation.
    dollars = min(float(dollars), MAX_ORDER)
    risk = risk_agent.evaluate(edge, dollars, daily_spent=daily_spent, open_exposure=0.0)

    if not liquidity["passed"]:
        raise HTTPException(400, f"Liquidity check failed: {liquidity['reason']}")
    if not risk["passed"]:
        raise HTTPException(400, "Risk check failed: " + "; ".join(risk["problems"]))

    order = execution_agent.prepare(ticker, data["yes_ask"], dollars)
    token = secrets.token_urlsafe(24)
    pending_orders[token] = {
        **order,
        "title": market.get("title"),
        "estimated_probability": probability,
        "edge": edge,
    }
    return RedirectResponse(url=f"/approve/{token}", status_code=303)


@app.get("/approve/{token}", response_class=HTMLResponse)
def approve_page(request: Request, token: str):
    order = pending_orders.get(token)
    if not order:
        raise HTTPException(404, "Approval request expired or not found.")
    return templates.TemplateResponse("approve.html", {
        "request": request,
        "token": token,
        "order": order,
        "env": ENV,
        "live": LIVE_TRADING,
    })


@app.post("/execute/{token}")
def execute(token: str):
    global daily_spent
    order = pending_orders.pop(token, None)
    if not order:
        raise HTTPException(404, "Approval request expired or already used.")

    client_order_id = str(uuid.uuid4())

    # If live trading isn't explicitly on, record a paper order only.
    if not LIVE_TRADING:
        result = {
            "mode": "paper",
            "client_order_id": client_order_id,
            **order,
        }
        paper_log.append(result)
        daily_spent += order["estimated_cost"]
        return RedirectResponse(url="/?paper=1", status_code=303)

    # A production order can only happen when both controls say production/live.
    if ENV != "production":
        raise HTTPException(
            400,
            "LIVE_TRADING=true but KALSHI_ENV is not production. Refusing to submit."
        )

    result = client.create_order(
        order["ticker"],
        order["price"],
        order["count"],
        client_order_id,
    )
    daily_spent += order["estimated_cost"]
    paper_log.append({"mode": "live", "response": result, **order})
    return RedirectResponse(url="/?live=1", status_code=303)


@app.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request):
    result = portfolio_agent.run(client)
    return templates.TemplateResponse("portfolio.html", {
        "request": request,
        "result": result,
        "env": ENV,
    })
