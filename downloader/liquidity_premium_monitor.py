#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Liquidity Premium Monitor (Weekly + 3M Daily, with Price Curves)
----------------------------------------------------------------
Features:
- Fetch only daily data (filtered by --start)
- Derive weekly from daily (no separate fetch)
- High-response LP Score (daily & weekly)
- Single figure with two panels:
    Upper: Weekly LP + Price since start (dual y-axes)
    Lower: Daily LP + Price over last 3 months (dual y-axes)
- Threshold guide lines at 1.2 / 1.5 / 2.0
"""

import argparse, os, sys, json
import pandas as pd, numpy as np, matplotlib.pyplot as plt

try:
    import akshare as ak
except ImportError:
    ak = None

try:
    import yfinance as yf
except ImportError:
    yf = None


def normalize_symbol(symbol, market, provider):
    s = symbol.strip().upper()
    if market == "cn":
        if provider == "yf":
            if s.startswith(("6", "9")):
                return s + ".SS"
            elif s.startswith(("0", "3")):
                return s + ".SZ"
        return s
    elif market == "hk":
        if provider == "yf":
            digits = ''.join([c for c in s if c.isdigit()])
            return digits.zfill(4) + ".HK"
        return s.zfill(5)
    else:
        return s


def guess_market(symbol):
    s = symbol.strip().upper()
    if s.endswith(".HK") or (s.isdigit() and len(s) in (4, 5)):
        return "hk"
    if len(s) == 6 and s[0].isdigit():
        return "cn"
    return "us"


def fetch_daily_data(symbol, market, start):
    df = None
    if ak and market in ("cn", "hk"):
        try:
            sym_ak = normalize_symbol(symbol, market, "ak")
            if market == "cn":
                df = ak.stock_zh_a_hist(sym_ak, period="daily", start_date=start.replace("-", ""), end_date="")
                df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                   "最高": "high", "最低": "low", "成交量": "volume"}, inplace=True)
            elif market == "hk":
                df = ak.stock_hk_hist(sym_ak, period="daily", adjust="")
                df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                   "最高": "high", "最低": "low", "成交量": "volume"}, inplace=True)
            df["date"] = pd.to_datetime(df["date"])
            df = df[df["date"] >= pd.to_datetime(start)]
            df = df[["date", "open", "high", "low", "close", "volume"]]
        except Exception:
            df = None

    if (df is None or df.empty) and yf:
        try:
            sym_yf = normalize_symbol(symbol, market, "yf")
            ticker = yf.Ticker(sym_yf)
            hist = ticker.history(start=start)
            df = hist.reset_index().rename(columns={
                "Date": "date", "Open": "open", "High": "high",
                "Low": "low", "Close": "close", "Volume": "volume"
            })
        except Exception:
            df = None

    return df


def resample_ohlcv(df, agg="weekly"):
    if agg == "daily":
        return df.copy()
    rule = {"weekly": "W-FRI", "monthly": "ME"}[agg]
    dfr = df.set_index("date").sort_index()
    o = dfr["open"].resample(rule).first()
    h = dfr["high"].resample(rule).max()
    l = dfr["low"].resample(rule).min()
    c = dfr["close"].resample(rule).last()
    v = dfr["volume"].resample(rule).sum()
    out = pd.concat([o, h, l, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna().reset_index()


def compute_indicators(df, agg="daily"):
    dfa = resample_ohlcv(df, agg)
    dfa["ret"] = dfa["close"].pct_change()

    short_span, long_span, roll_win = 2, 8, 10
    ew_short = dfa["volume"].ewm(span=short_span, adjust=False).mean()
    ew_long = dfa["volume"].ewm(span=long_span, adjust=False).mean()
    vol_ew_ratio = ew_short / ew_long

    vol_med = dfa["volume"].rolling(roll_win, min_periods=roll_win // 2, center=True).median()
    vol_rel_med = dfa["volume"] / vol_med
    vol_component = 0.5 * vol_ew_ratio + 0.5 * vol_rel_med
    vol_component = vol_component.rolling(2, min_periods=2).mean()

    annual = 252 if agg == "daily" else 52
    rv_fast = dfa["ret"].rolling(2, min_periods=2).std() * np.sqrt(annual)
    rv_slow = dfa["ret"].rolling(8, min_periods=4).std() * np.sqrt(annual)
    vol_ratio = (rv_fast / rv_slow).rolling(2, min_periods=2).mean()

    ma = dfa["close"].rolling(10, min_periods=5).mean()
    valuation = (dfa["close"] / ma).rolling(2, center=True).mean()

    roll_max = dfa["close"].rolling(10, min_periods=5).max()
    roll_min = dfa["close"].rolling(10, min_periods=5).min()
    sentiment = ((dfa["close"] - roll_min) / (roll_max - roll_min)).clip(0, 1)
    sentiment = sentiment.rolling(2, min_periods=2, center=True).mean()

    dfa["vol_change"] = dfa["volume"].pct_change().clip(-2, 2).fillna(0)
    dfa["vol_amp"] = vol_component
    dfa["vol_ratio"] = vol_ratio
    dfa["valuation"] = valuation
    dfa["sentiment"] = sentiment
    return dfa


def compute_score(df, w_vol=0.4, w_var=0.3, w_val=0.2, w_sent=0.1):
    df = df.copy()
    def norm(s):
        return s.clip(lower=0.3, upper=4.0)
    V = norm(df["vol_amp"])
    R = norm(df["vol_ratio"])
    VAL = norm(df["valuation"])
    S = df["sentiment"].fillna(0.5) * 2
    score = w_vol * V + w_var * R + w_val * VAL + w_sent * S + 0.15 * df["vol_change"]
    df["lp_score"] = score.rolling(2, min_periods=2, center=True).mean()
    return df


def plot_dual_panel(df_d, df_w, symbol, market, start, outdir="output"):
    os.makedirs(outdir, exist_ok=True)
    cutoff = df_d["date"].max() - pd.Timedelta(days=90)
    df_recent = df_d[df_d["date"] >= cutoff]

    fig, (ax_top, ax_bottom) = plt.subplots(
    2, 1,
    figsize=(11, 7),
    sharex=False,
    gridspec_kw={'height_ratios': [2, 1.4], 'hspace': 0.25},
    constrained_layout=True   # ✅ 关键修改
)


    # Upper panel: weekly price + LP
    ax_price_top = ax_top
    ax_lp_top = ax_price_top.twinx()
    ax_price_top.plot(df_w["date"], df_w["close"], color="tab:blue", label="Price (Weekly Close)", linewidth=1.2)
    ax_price_top.set_ylabel("Price", color="tab:blue")
    ax_lp_top.plot(df_w["date"], df_w["lp_score"], color="tab:orange", label="LP (Weekly)", linewidth=1.4)
    ax_lp_top.set_ylabel("LP Score (Weekly)", color="tab:orange")
    for thr in [1.2, 1.5, 2.0]:
        ax_lp_top.axhline(thr, color="gray", linestyle="--", linewidth=0.8)
    lines1, labels1 = ax_price_top.get_legend_handles_labels()
    lines2, labels2 = ax_lp_top.get_legend_handles_labels()
    ax_price_top.legend(lines1 + lines2, labels1 + labels2, loc="upper left", frameon=False)
    ax_price_top.set_title(f"{symbol} ({market.upper()}) Weekly LP + Price since {start}")

    # Lower panel: daily price + LP (last 3M)
    ax_price_bot = ax_bottom
    ax_lp_bot = ax_price_bot.twinx()
    ax_price_bot.plot(df_recent["date"], df_recent["close"], color="tab:blue", label="Price (Daily Close)", linewidth=1.1)
    ax_price_bot.set_ylabel("Price", color="tab:blue")
    ax_lp_bot.plot(df_recent["date"], df_recent["lp_score"], color="tab:green", label="LP (Daily, last 3M)", linewidth=1.3)
    ax_lp_bot.set_ylabel("LP Score (Daily)", color="tab:green")
    for thr in [1.2, 1.5, 2.0]:
        ax_lp_bot.axhline(thr, color="gray", linestyle="--", linewidth=0.8)
    lines3, labels3 = ax_price_bot.get_legend_handles_labels()
    lines4, labels4 = ax_lp_bot.get_legend_handles_labels()
    ax_price_bot.legend(lines3 + lines4, labels3 + labels4, loc="upper left", frameon=False)


    out_path = os.path.join(outdir, f"{symbol}_{market}_lp_dual_zoom.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Liquidity Premium Monitor (Weekly + 3M Daily with Price)")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", default="auto", choices=["auto", "cn", "hk", "us"])
    parser.add_argument("--start", default="2015-01-01")
    args = parser.parse_args()

    market = args.market if args.market != "auto" else guess_market(args.symbol)
    df = fetch_daily_data(args.symbol, market, args.start)
    if df is None or df.empty:
        print(f"[Error] Failed to fetch data for {args.symbol}")
        sys.exit(1)

    df_d = compute_score(compute_indicators(df, "daily"))
    df_w = compute_score(compute_indicators(df, "weekly"))

    os.makedirs("output", exist_ok=True)
    csv_path = os.path.join("output", f"{args.symbol}_{market}_lp_dual.csv")
    pd.concat([df_d.assign(freq="daily"), df_w.assign(freq="weekly")]).to_csv(csv_path, index=False)

    png_path = plot_dual_panel(df_d, df_w, args.symbol, market, args.start)
    print(json.dumps({"csv": csv_path, "png": png_path, "market": market}))


if __name__ == "__main__":
    main()
