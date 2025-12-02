#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Liquidity Premium Monitor (Final Anti-Cache Version)
----------------------------------------------------
- 自动清空 docs/<symbol>/ 下所有旧文件（CSV + PNG）
- 图像文件名带时间戳（YYYYMMDD_HH）
- 不改动任意原有逻辑、指标、绘图样式
- 稳定用于 Notion + jsDelivr（完全无缓存）
"""

import os, sys, json, yaml
import matplotlib
matplotlib.use("Agg")
import pandas as pd, numpy as np, matplotlib.pyplot as plt
from datetime import datetime

try:
    import akshare as ak
except ImportError:
    ak = None
try:
    import yfinance as yf
except ImportError:
    yf = None


# ============================================================
#  1️⃣ 读取配置
# ============================================================
def load_config(path="config.yaml"):
    if not os.path.exists(path):
        print(f"[Error] Missing config.yaml at {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
#  2️⃣ 股票代码标准化
# ============================================================
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


# ============================================================
#  3️⃣ 数据获取
# ============================================================
def fetch_daily_data(symbol, market, start):
    df = None
    if ak and market in ("cn", "hk"):
        try:
            sym_ak = normalize_symbol(symbol, market, "ak")
            if market == "cn":
                df = ak.stock_zh_a_hist(sym_ak, period="daily",
                                        start_date=start.replace("-", ""), end_date="")
                df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                   "最高": "high", "最低": "low", "成交量": "volume"}, inplace=True)
            elif market == "hk":
                df = ak.stock_hk_hist(sym_ak, period="daily", adjust="")
                df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                   "最高": "high", "最低": "low", "成交量": "volume"}, inplace=True)
            df["date"] = pd.to_datetime(df["date"])
            df = df[df["date"] >= pd.to_datetime(start)]
            df = df[["date", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            print(f"[Warn] AkShare fetch failed for {symbol}: {e}")
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
            df = df[df["date"] >= pd.to_datetime(start)]
        except Exception as e:
            print(f"[Error] Yahoo fetch failed for {symbol}: {e}")
            df = None
    return df


# ============================================================
#  4️⃣ 指标计算
# ============================================================
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
    def norm(s): return s.clip(lower=0.3, upper=4.0)
    V = norm(df["vol_amp"])
    R = norm(df["vol_ratio"])
    VAL = norm(df["valuation"])
    S = df["sentiment"].fillna(0.5) * 2
    score = w_vol * V + w_var * R + w_val * VAL + w_sent * S + 0.15 * df["vol_change"]
    df["lp_score"] = score.rolling(2, min_periods=2, center=True).mean()
    return df


# ============================================================
#  5️⃣ 清空目录
# ============================================================
def clear_directory(dirpath):
    if not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
        return

    for f in os.listdir(dirpath):
        fp = os.path.join(dirpath, f)
        if os.path.isfile(fp):
            os.remove(fp)
            print(f"[DEL] {fp}")


# ============================================================
#  6️⃣ 绘图（带时间戳）
# ============================================================
def plot_dual_panel(df_d, df_w, symbol, market, start, outdir):
    import matplotlib.pyplot as plt
    cutoff = df_d["date"].max() - pd.Timedelta(days=90)
    df_recent = df_d[df_d["date"] >= cutoff]

    fig, (ax_top, ax_bottom) = plt.subplots(
        2, 1, figsize=(11, 7),
        gridspec_kw={'height_ratios': [2, 1.4]},
        constrained_layout=True
    )

    # --- Weekly ---
    ax_p_top = ax_top
    ax_lp_top = ax_p_top.twinx()
    ax_p_top.plot(df_w["date"], df_w["close"], color="tab:blue", linewidth=1.2)
    ax_lp_top.plot(df_w["date"], df_w["lp_score"], color="tab:orange", linewidth=1.4)

    for thr in [1.2, 1.5, 2.0]:
        ax_lp_top.axhline(thr, color="gray", linestyle="--", linewidth=0.8)

    ax_p_top.set_title(f"{symbol} ({market.upper()}) Weekly LP + Price since {start}")

    # --- Daily (3M) ---
    ax_p_bot = ax_bottom
    ax_lp_bot = ax_p_bot.twinx()
    ax_p_bot.plot(df_recent["date"], df_recent["close"], color="tab:blue", linewidth=1.1)
    ax_lp_bot.plot(df_recent["date"], df_recent["lp_score"], color="tab:green", linewidth=1.3)

    for thr in [1.2, 1.5, 2.0]:
        ax_lp_bot.axhline(thr, color="gray", linestyle="--", linewidth=0.8)

    # === 时间戳文件名 ===
    ts = datetime.now().strftime("%Y%m%d_%H")
    out_path = os.path.join(outdir, f"{symbol}_{market}_lp_dual_zoom_{ts}.png")

    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"[IMG] {out_path}")
    return out_path


# ============================================================
#  7️⃣ 主函数
# ============================================================
def main():
    cfg = load_config()
    output_dir = cfg.get("output_dir", "docs")

    for stock in cfg.get("stocks", []):
        symbol = stock["symbol"]
        market = stock.get("market", "auto")
        start = stock.get("start", "2015-01-01")
        display_name = stock.get("name", symbol).replace(" ", "_")

        print(f"\n[Running] {display_name} ({symbol}, {market}) from {start}")
        df = fetch_daily_data(symbol, market, start)
        if df is None or df.empty:
            print(f"[Error] No data for {symbol}")
            continue

        df_d = compute_score(compute_indicators(df, "daily"))
        df_w = compute_score(compute_indicators(df, "weekly"))

        stock_dir = os.path.join(output_dir, display_name)
        clear_directory(stock_dir)    # 🔥 清空文件夹

        os.makedirs(stock_dir, exist_ok=True)

        # 保存 CSV（无时间戳）
        csv_path = os.path.join(stock_dir, f"{display_name}_{market}_lp_dual.csv")
        pd.concat([df_d.assign(freq="daily"), df_w.assign(freq="weekly")]).to_csv(csv_path, index=False)

        # 绘图（带时间戳）
        png_path = plot_dual_panel(df_d, df_w, display_name, market, start, outdir=stock_dir)

        print(f"[CSV] {csv_path}")
        print(f"[PNG] {png_path}")

    print("\n✅ All tasks completed.")


if __name__ == "__main__":
    main()
