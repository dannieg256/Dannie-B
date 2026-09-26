# Kalshi 9-Agent Starter

A phone-friendly FastAPI dashboard that scans Kalshi markets, scores trade candidates,
checks risk, and requires manual approval before an order is submitted.

## Important defaults

- Demo environment by default.
- Live trading is OFF by default.
- Every order requires a manual approval action.
- Risk limits are enforced server-side.
- Never upload your Kalshi private key into a chat or paste it into the browser UI.

## The 9 agents

1. MarketScannerAgent
2. RulesAgent
3. DataAgent
4. ProbabilityAgent
5. ValueAgent
6. LiquidityAgent
7. RiskAgent
8. PortfolioAgent
9. ExecutionAgent

This starter does NOT pretend it can magically predict outcomes. Its probability agent
uses either:
- a probability you enter yourself, OR
- a conservative baseline based on the market midpoint when no external forecast is supplied.

You can later add sports/weather/economic data sources to DataAgent.

## Setup

### 1. Install Python 3.11+

On a cloud host (Render, Railway, Fly.io, VPS, etc.):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create a Kalshi DEMO API key

In the Kalshi demo account, create an API key and download the private PEM file.

Put the PEM file beside this project as:

```text
kalshi-private-key.pem
```

Never commit that key to Git.

### 3. Configure

```bash
cp .env.example .env
```

Fill in `KALSHI_API_KEY_ID`.

Keep:

```text
KALSHI_ENV=demo
LIVE_TRADING=false
```

until you have tested the system.

### 4. Run

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open the displayed URL from Safari on your iPhone.

## Live mode

Only after demo testing:

```text
KALSHI_ENV=production
LIVE_TRADING=true
```

Use a PRODUCTION API key; demo and production credentials are separate.

The dashboard still requires an explicit manual approval for every submitted order.

## Suggested deployment

For iPhone-only use, deploy this folder to a cloud host. Store the private key and
environment variables as server secrets. Do not embed API credentials in client-side
JavaScript.

## API notes

This starter uses Kalshi's current Trade API V2 structure:
- Market list: `GET /markets`
- Market orderbook: `GET /markets/{ticker}/orderbook`
- Balance: `GET /portfolio/balance`
- Positions: `GET /portfolio/positions`
- Create order V2: `POST /portfolio/events/orders`

Order requests use the V2 single-book structure (`side=bid`, dollar `price`).
