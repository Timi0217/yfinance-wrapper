from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from datetime import datetime
import yfinance as yf
from typing import Optional

app = FastAPI(title="yfinance Wrapper API")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.get("/quote")
async def get_quote(symbol: str = Query(..., description="Stock symbol (e.g., AAPL)")):
    """Get current stock quote with price, change, volume, and basic info"""
    try:
        ticker = yf.Ticker(symbol)

        # Try to get data from both info and fast_info
        try:
            info = ticker.info
            fast_info = ticker.fast_info
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found or data unavailable")

        # Check if we got valid data
        if not info or info.get('regularMarketPrice') is None:
            if not fast_info or not hasattr(fast_info, 'last_price'):
                raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

        # Build response using available data
        response = {
            "symbol": symbol.upper(),
            "price": getattr(fast_info, 'last_price', None) or info.get('regularMarketPrice') or info.get('currentPrice'),
            "change": info.get('regularMarketChange'),
            "change_pct": info.get('regularMarketChangePercent'),
            "volume": getattr(fast_info, 'last_volume', None) or info.get('regularMarketVolume') or info.get('volume'),
            "market_cap": info.get('marketCap'),
            "currency": info.get('currency') or info.get('financialCurrency'),
            "exchange": getattr(fast_info, 'exchange', None) or info.get('exchange'),
            "name": info.get('longName') or info.get('shortName'),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"yfinance service error: {str(e)}")


@app.get("/history")
async def get_history(
    symbol: str = Query(..., description="Stock symbol (e.g., AAPL)"),
    period: str = Query("6mo", description="Period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd, max")
):
    """Get historical OHLCV data"""
    valid_periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"]

    if period not in valid_periods:
        raise HTTPException(status_code=400, detail=f"Invalid period. Must be one of: {', '.join(valid_periods)}")

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)

        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No data found for symbol '{symbol}'")

        # Convert DataFrame to list of dicts
        data = []
        for date, row in hist.iterrows():
            data.append({
                "date": date.isoformat(),
                "open": float(row['Open']) if not pd.isna(row['Open']) else None,
                "high": float(row['High']) if not pd.isna(row['High']) else None,
                "low": float(row['Low']) if not pd.isna(row['Low']) else None,
                "close": float(row['Close']) if not pd.isna(row['Close']) else None,
                "volume": int(row['Volume']) if not pd.isna(row['Volume']) else None
            })

        return {
            "symbol": symbol.upper(),
            "period": period,
            "data": data,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"yfinance service error: {str(e)}")


@app.get("/fundamentals")
async def get_fundamentals(symbol: str = Query(..., description="Stock symbol (e.g., AAPL)")):
    """Get company fundamentals and financial metrics"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        if not info or not info.get('symbol'):
            raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

        response = {
            "symbol": symbol.upper(),
            "pe_ratio": info.get('trailingPE') or info.get('forwardPE'),
            "forward_pe": info.get('forwardPE'),
            "eps": info.get('trailingEps') or info.get('epsTrailingTwelveMonths'),
            "revenue": info.get('totalRevenue'),
            "market_cap": info.get('marketCap'),
            "dividend_yield": info.get('dividendYield'),
            "beta": info.get('beta'),
            "sector": info.get('sector'),
            "industry": info.get('industry'),
            "description": info.get('longBusinessSummary'),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"yfinance service error: {str(e)}")


@app.get("/forex")
async def get_forex(
    from_currency: str = Query(..., description="Source currency (e.g., USD)"),
    to_currency: str = Query(..., description="Target currency (e.g., EUR)"),
    amount: float = Query(1.0, description="Amount to convert")
):
    """Get forex conversion rate and converted amount"""
    try:
        # yfinance uses format: USDEUR=X
        forex_symbol = f"{from_currency.upper()}{to_currency.upper()}=X"

        ticker = yf.Ticker(forex_symbol)

        # Get current rate
        try:
            fast_info = ticker.fast_info
            rate = getattr(fast_info, 'last_price', None)
        except:
            rate = None

        if rate is None:
            info = ticker.info
            rate = info.get('regularMarketPrice') or info.get('bid')

        if rate is None:
            raise HTTPException(status_code=404, detail=f"Forex pair '{from_currency}/{to_currency}' not found")

        converted_amount = rate * amount

        return {
            "from_currency": from_currency.upper(),
            "to_currency": to_currency.upper(),
            "rate": float(rate),
            "amount": float(amount),
            "converted_amount": float(converted_amount),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"yfinance service error: {str(e)}")


# Import pandas for isna check in history endpoint
import pandas as pd


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
