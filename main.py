"""
Yahoo Finance Wrapper — direct HTTP API, no yfinance library.

Uses Yahoo Finance v8 chart API for quotes, history, and forex.
Fundamentals are handled by the Finnhub wrapper (this wrapper does not
need to duplicate that functionality).
"""

from fastapi import FastAPI, HTTPException, Query
from datetime import datetime, timezone
import httpx
import os

app = FastAPI(title="Yahoo Finance Wrapper API")

_YF_BASE = "https://query1.finance.yahoo.com"
_UA = "Mozilla/5.0 (compatible; ChekkAgent/1.0)"
_TIMEOUT = float(os.environ.get("YF_TIMEOUT", "8"))

# Re-usable async client (connection pooling)
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _UA},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )
    return _client


async def _chart(symbol: str, range_: str = "1d", interval: str = "1d") -> dict:
    """Call Yahoo Finance v8 chart API and return the first result."""
    client = await _get_client()
    url = f"{_YF_BASE}/v8/finance/chart/{symbol}"
    params = {"range": range_, "interval": interval}
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    chart = data.get("chart", {})
    error = chart.get("error")
    if error:
        raise HTTPException(status_code=404, detail=error.get("description", str(error)))
    results = chart.get("result", [])
    if not results:
        raise HTTPException(status_code=404, detail=f"No data for symbol '{symbol}'")
    return results[0]


# ── Endpoints ────────────────────────────────────────────────────────────


@app.get("/")
async def root():
    return {
        "name": "Yahoo Finance Wrapper",
        "version": "2.0",
        "description": "Stock quotes, historical OHLCV, and forex via Yahoo Finance HTTP API",
        "endpoints": [
            {"path": "/quote?symbol=AAPL", "description": "Current stock quote"},
            {"path": "/history?symbol=AAPL&period=6mo", "description": "Historical OHLCV"},
            {"path": "/fundamentals?symbol=AAPL", "description": "Basic fundamentals from chart meta"},
            {"path": "/forex?from_currency=USD&to_currency=EUR&amount=100", "description": "Forex rate"},
            {"path": "/health", "description": "Health check"},
        ],
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/quote")
async def get_quote(symbol: str = Query(..., description="Stock symbol (e.g. AAPL)")):
    """Current price quote via v8 chart API."""
    try:
        result = await _chart(symbol.upper(), range_="1d", interval="1d")
        meta = result.get("meta", {})

        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")

        change = round(price - prev_close, 4) if price and prev_close else None
        change_pct = round((change / prev_close) * 100, 4) if change and prev_close else None

        # Try to pull today's high/low/open from indicators
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        opens = quotes.get("open", [])
        volumes = quotes.get("volume", [])

        return {
            "symbol": meta.get("symbol", symbol.upper()),
            "current_price": price,
            "change": change,
            "percent_change": change_pct,
            "high": highs[-1] if highs else None,
            "low": lows[-1] if lows else None,
            "open": opens[-1] if opens else None,
            "previous_close": prev_close,
            "volume": volumes[-1] if volumes else None,
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "name": meta.get("longName") or meta.get("shortName"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Yahoo Finance error: {e}")


@app.get("/history")
async def get_history(
    symbol: str = Query(..., description="Stock symbol"),
    period: str = Query("6mo", description="1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd, max"),
):
    """Historical OHLCV data."""
    valid = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"}
    if period not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid period. Use one of: {', '.join(sorted(valid))}")

    # Pick interval based on period length
    interval_map = {
        "1d": "5m", "5d": "30m",
        "1mo": "1d", "3mo": "1d", "6mo": "1d",
        "1y": "1d", "2y": "1wk", "5y": "1wk",
        "ytd": "1d", "max": "1mo",
    }
    interval = interval_map.get(period, "1d")

    try:
        result = await _chart(symbol.upper(), range_=period, interval=interval)
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]

        opens = quotes.get("open", [])
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        closes = quotes.get("close", [])
        volumes = quotes.get("volume", [])

        data = []
        for i, ts in enumerate(timestamps):
            data.append({
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": round(opens[i], 4) if i < len(opens) and opens[i] is not None else None,
                "high": round(highs[i], 4) if i < len(highs) and highs[i] is not None else None,
                "low": round(lows[i], 4) if i < len(lows) and lows[i] is not None else None,
                "close": round(closes[i], 4) if i < len(closes) and closes[i] is not None else None,
                "volume": volumes[i] if i < len(volumes) and volumes[i] is not None else None,
            })

        return {
            "symbol": symbol.upper(),
            "period": period,
            "interval": interval,
            "data_points": len(data),
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Yahoo Finance error: {e}")


@app.get("/fundamentals")
async def get_fundamentals(symbol: str = Query(..., description="Stock symbol")):
    """Basic fundamentals from chart metadata (PE, market cap, 52w range).

    For full fundamentals, use the Finnhub wrapper.
    """
    try:
        result = await _chart(symbol.upper(), range_="1y", interval="1d")
        meta = result.get("meta", {})
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        closes = [c for c in quotes.get("close", []) if c is not None]

        return {
            "symbol": meta.get("symbol", symbol.upper()),
            "name": meta.get("longName") or meta.get("shortName"),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "current_price": meta.get("regularMarketPrice"),
            "previous_close": meta.get("chartPreviousClose"),
            "52w_high": max(closes) if closes else None,
            "52w_low": min(closes) if closes else None,
            "data_granularity": meta.get("dataGranularity"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Yahoo Finance error: {e}")


@app.get("/forex")
async def get_forex(
    from_currency: str = Query(..., description="Source currency (e.g. USD)"),
    to_currency: str = Query(..., description="Target currency (e.g. EUR)"),
    amount: float = Query(1.0, description="Amount to convert"),
):
    """Forex conversion rate via Yahoo Finance currency pairs."""
    pair = f"{from_currency.upper()}{to_currency.upper()}=X"
    try:
        result = await _chart(pair, range_="1d", interval="1d")
        meta = result.get("meta", {})
        rate = meta.get("regularMarketPrice")

        if rate is None:
            raise HTTPException(
                status_code=404,
                detail=f"Forex pair {from_currency}/{to_currency} not found",
            )

        return {
            "from_currency": from_currency.upper(),
            "to_currency": to_currency.upper(),
            "rate": float(rate),
            "amount": float(amount),
            "converted_amount": round(float(rate) * amount, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Yahoo Finance error: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
