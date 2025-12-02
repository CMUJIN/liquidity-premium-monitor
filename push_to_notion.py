#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Push LP Monitor PNGs to Notion (Right-side Outline Version)
-----------------------------------------------------------
- 与期货版 push_to_notion 一致
- 每个股票使用 heading_2，Notion 自动生成右侧目录
- 找最新 *_YYYYMMDD_HH.png
- CDN: jsDelivr（无缓存问题）
"""

import os
import yaml
from datetime import datetime
from notion_client import Client
import glob

# -----------------------------
# 固定 CDN 路径
# -----------------------------
BASE_CDN = "https://cdn.jsdelivr.net/gh/CMUJIN/liquidity-premium-monitor@main/docs"

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_PAGE = os.getenv("NOTION_PAGE_ID")

notion = Client(auth=NOTION_TOKEN)


# -----------------------------
# Utility
# -----------------------------
def get_latest(pattern):
    """匹配 *_YYYYMMDD_HH.png"""
    lst = glob.glob(pattern)
    if not lst:
        return None
    return max(lst, key=os.path.getmtime)


def file_time(path):
    if not path or not os.path.exists(path):
        return "N/A"
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")


def safe_heading(text):
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": str(text)}}]
        }
    }


def safe_para(text):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": str(text)}}]
        }
    }


# -----------------------------
# 清空 Notion 页面
# -----------------------------
def clear_page(page_id):
    try:
        children = notion.blocks.children.list(page_id)["results"]
        for c in children:
            # 保留子页面 / 数据库
            if c["type"] in ("child_page", "child_database"):
                continue
            notion.blocks.delete(c["id"])
        print("[INFO] Notion page cleared.")
    except Exception as e:
        print(f"[WARN] clear_page failed: {e}")


# -----------------------------
# 主构建逻辑（与期货版一致）
# -----------------------------
def push_to_notion():

    cfg = yaml.safe_load(open("config.yaml", "r", encoding="utf-8"))
    outdir = cfg.get("output_dir", "docs")

    # 扫描所有股票子目录
    stocks = []
    for name in os.listdir(outdir):
        d = os.path.join(outdir, name)
        if os.path.isdir(d):
            stocks.append(name)

    stocks = sorted(stocks)
    print(f"[INFO] Found stocks: {stocks}")

    # 清空 Notion 页面
    clear_page(NOTION_PAGE)

    blocks = []

    for stock in stocks:

        # ===== 寻找最新 trend_v6 图 =====
        trend_path = get_latest(f"{outdir}/{stock}/{stock}_trend_v6*.png")
        trend_file = os.path.basename(trend_path) if trend_path else None
        trend_url = f"{BASE_CDN}/{stock}/{trend_file}" if trend_file else None

        # ===== 寻找最新 lp_dual_zoom 图 =====
        lp_path = get_latest(f"{outdir}/{stock}/{stock}_*_lp_dual_zoom*.png")
        lp_file = os.path.basename(lp_path) if lp_path else None
        lp_url = f"{BASE_CDN}/{stock}/{lp_file}" if lp_file else None

        # ===== Header （右侧目录由这个自动生成）=====
        blocks.append(safe_heading(f"📈 {stock} LP Monitor"))

        blocks.append(safe_para(f"🕒 Updated: {file_time(lp_path)}"))

        # ===== Trend 图片 =====
        if trend_url:
            blocks.append({
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": trend_url}}
            })

        # ===== LP Zoom 图片 =====
        if lp_url:
            blocks.append({
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": lp_url}}
            })

    # 一次性追加
    notion.blocks.children.append(NOTION_PAGE, children=blocks)
    print("[DONE] LP monitor pushed to Notion with right-side outline.")


if __name__ == "__main__":
    push_to_notion()
