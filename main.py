"""
Yahoo Finance Wrapper — direct HTTP API, no yfinance library.

Uses Yahoo Finance v8 chart API for quotes, history, and forex.
Fundamentals are handled by the Finnhub wrapper (this wrapper does not
need to duplicate that functionality).
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
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


# ── HTML Home Page ──────────────────────────────────────────────────────

HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yahoo Finance Wrapper</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#fff;font-family:system-ui,-apple-system,sans-serif;padding:40px 20px;min-height:100vh}
.container{max-width:640px;margin:0 auto;opacity:0;animation:fadeIn .6s ease forwards}
@keyframes fadeIn{to{opacity:1}}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.title{font:italic 28px ui-monospace,monospace;color:#C2185B}
.badge{background:rgba(34,197,94,.15);color:#22c55e;font-size:11px;padding:4px 10px;border-radius:12px;font-weight:600;letter-spacing:.5px}
.subtitle{color:#888;font-size:14px;margin-bottom:32px}
.card{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:16px;padding:20px;margin-bottom:24px}
.section-title{font-size:11px;font-weight:700;letter-spacing:1.5px;color:#666;margin-bottom:16px}
.stock-row,.forex-row{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.stock-row:last-child,.forex-row:last-child{border:none}
.stock-left{flex:1}
.stock-symbol{font-weight:700;font-size:15px;margin-bottom:2px}
.stock-name{color:#666;font-size:12px}
.stock-right{text-align:right}
.stock-price{font:600 15px ui-monospace,monospace;margin-bottom:2px}
.stock-change{font:500 12px ui-monospace,monospace}
.change-up{color:#22c55e}
.change-down{color:#ef4444}
.forex-pair{font-weight:600;font-size:14px}
.forex-rate{font:600 14px ui-monospace,monospace;color:#C2185B}
.form-section{margin-top:32px}
.input-group{display:flex;gap:8px;margin-bottom:12px}
.input{flex:1;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:12px 16px;color:#fff;font-size:14px;font-family:ui-monospace,monospace}
.input:focus{outline:none;border-color:#C2185B}
.btn{background:#C2185B;color:#fff;border:none;border-radius:8px;padding:12px 24px;font-size:14px;font-weight:600;cursor:pointer;transition:opacity .2s}
.btn:hover{opacity:.85}
.try-line{color:#666;font-size:13px;display:flex;gap:8px;flex-wrap:wrap}
.try-link{color:#C2185B;cursor:pointer;transition:opacity .2s}
.try-link:hover{opacity:.7}
.result{margin-top:16px;padding:16px;background:rgba(194,24,91,.1);border:1px solid rgba(194,24,91,.3);border-radius:8px;font:13px ui-monospace,monospace;color:#eee;white-space:pre-wrap;display:none}
.loading{color:#666;font-size:13px;margin-top:8px;display:none}
.error{color:#ef4444}
</style>
</head>
<body>
<div class="container">
<div class="header">
<div class="title">Yahoo Finance</div>
<div class="badge" id="health">HEALTHY</div>
</div>
<div class="subtitle">Stock quotes, historical OHLCV, and forex rates</div>

<div class="card">
<div class="section-title">MARKET OVERVIEW</div>
<div id="market"></div>
</div>

<div class="card">
<div class="section-title">FOREX</div>
<div id="forex"></div>
</div>

<div class="form-section">
<div class="input-group">
<input class="input" id="symbolInput" placeholder="AAPL" maxlength="10">
<button class="btn" onclick="fetchQuote()">\\u2192 quote</button>
</div>
<div class="try-line">
<span>Try:</span>
<span class="try-link" onclick="trySymbol('TSLA')">TSLA</span> \\u00B7
<span class="try-link" onclick="trySymbol('MSFT')">MSFT</span> \\u00B7
<span class="try-link" onclick="trySymbol('GOOGL')">GOOGL</span> \\u00B7
<span class="try-link" onclick="trySymbol('NVDA')">NVDA</span> \\u00B7
<span class="try-link" onclick="trySymbol('META')">META</span>
</div>
<div class="loading" id="loading">Fetching...</div>
<div class="result" id="result"></div>
</div>
</div>

<script>
const STOCKS = ['SPY','QQQ','AAPL','TSLA'];
const STOCK_NAMES = {SPY:'S&P 500 ETF',QQQ:'NASDAQ 100 ETF',AAPL:'Apple Inc.',TSLA:'Tesla Inc.'};
const FOREX_PAIRS = [
  {from:'USD',to:'EUR',label:'USD/EUR'},
  {from:'USD',to:'GBP',label:'USD/GBP'},
  {from:'USD',to:'JPY',label:'USD/JPY'}
];

async function loadData(){
  const healthP = fetch('/health').then(r=>r.json()).catch(()=>({status:'error'}));
  const quotesP = STOCKS.map(s=>fetch('/quote?symbol='+s).then(r=>r.json()).catch(()=>null));
  const forexP = FOREX_PAIRS.map(p=>fetch('/forex?from_currency='+p.from+'&to_currency='+p.to).then(r=>r.json()).catch(()=>null));

  const [health,...quotes] = await Promise.all([healthP,...quotesP,...forexP]);

  document.getElementById('health').textContent = health.status==='healthy'?'HEALTHY':'OFFLINE';
  document.getElementById('health').style.background = health.status==='healthy'?'rgba(34,197,94,.15)':'rgba(239,68,68,.15)';
  document.getElementById('health').style.color = health.status==='healthy'?'#22c55e':'#ef4444';

  const marketHtml = quotes.slice(0,4).map((q,i)=>{
    if(!q || !q.current_price) return '';
    const symbol = STOCKS[i];
    const name = STOCK_NAMES[symbol] || q.name || '';
    const price = '$' + q.current_price.toFixed(2);
    const change = q.change || 0;
    const changePct = q.percent_change || 0;
    const changeClass = change >= 0 ? 'change-up' : 'change-down';
    const changeText = (change >= 0 ? '+' : '') + change.toFixed(2) + ' (' + (changePct >= 0 ? '+' : '') + changePct.toFixed(2) + '%)';
    return '<div class="stock-row"><div class="stock-left"><div class="stock-symbol">'+symbol+'</div><div class="stock-name">'+name+'</div></div><div class="stock-right"><div class="stock-price">'+price+'</div><div class="stock-change '+changeClass+'">'+changeText+'</div></div></div>';
  }).join('');
  document.getElementById('market').innerHTML = marketHtml || '<div style="color:#666;font-size:13px">Failed to load market data</div>';

  const forexHtml = quotes.slice(4).map((fx,i)=>{
    if(!fx || !fx.rate) return '';
    const pair = FOREX_PAIRS[i];
    const rate = fx.rate.toFixed(4);
    return '<div class="forex-row"><div class="forex-pair">'+pair.label+'</div><div class="forex-rate">'+rate+'</div></div>';
  }).join('');
  document.getElementById('forex').innerHTML = forexHtml || '<div style="color:#666;font-size:13px">Failed to load forex data</div>';
}

function trySymbol(sym){
  document.getElementById('symbolInput').value = sym;
  fetchQuote();
}

async function fetchQuote(){
  const symbol = document.getElementById('symbolInput').value.trim().toUpperCase();
  if(!symbol) return;

  const loading = document.getElementById('loading');
  const result = document.getElementById('result');

  loading.style.display = 'block';
  result.style.display = 'none';

  try{
    const res = await fetch('/quote?symbol='+symbol);
    const data = await res.json();

    if(!res.ok){
      result.className = 'result error';
      result.textContent = 'Error: ' + (data.detail || 'Unknown error');
    } else {
      result.className = 'result';
      result.textContent = JSON.stringify(data, null, 2);
    }
  } catch(err){
    result.className = 'result error';
    result.textContent = 'Network error: ' + err.message;
  } finally {
    loading.style.display = 'none';
    result.style.display = 'block';
  }
}

document.getElementById('symbolInput').addEventListener('keypress', e=>{
  if(e.key==='Enter') fetchQuote();
});

loadData();
</script>
</body>
</html>
"""

# ── Endpoints ────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=HOME_HTML)


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
