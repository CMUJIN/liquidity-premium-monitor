#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Push LP Monitor PNGs to Notion Page (CDN Version + TOC)
-------------------------------------------------------
- 自动读取 docs/ 下股票子目录
- 每个股票区块前添加目录（可跳转）
- 每次推送前清空页面
- 图片引用 jsDelivr CDN（无缓存）
"""

import os, yaml
from datetime import datetime
from notion_client import Client


# -------------------------------------------------------
# 固定 CDN 前缀（不使用 raw.githubusercontent）
# -------------------------------------------------------
BASE_URL = "https://cdn.jsdelivr.net/gh/CMUJIN/liquidity-premium-monitor@main/docs"


def load_config(path="config.yaml"):
    if not os.path.exists(path):
        raise FileNotFoundError("Missing config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# -------------------------------------------------------
# 获取 docs/<symbol> 下所有 PNG 文件
# -------------------------------------------------------
def get_stock_pngs(output_dir):
    stocks = {}

    for stock_name in os.listdir(output_dir):
        stock_dir = os.path.join(output_dir, stock_name)

        if not os.path.isdir(stock_dir):
            continue

        pngs = []
        for f in os.listdir(stock_dir):
            if not f.endswith(".png"):
                continue

            full = os.path.join(stock_dir, f)
            rel = os.path.relpath(full, output_dir).replace("\\", "/")
            mtime = os.path.getmtime(full)

            pngs.append({
                "path": full,
                "rel": rel,
                "mtime": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "file": f
            })

        if pngs:
            stocks[stock_name] = sorted(pngs, key=lambda x: x["file"])

    return stocks  # dict: { "MAOTAI": [png1, png2], ... }


# -------------------------------------------------------
# 构建目录（自动跳转到对应 Heading）
# -------------------------------------------------------
def build_toc_block(stocks):
    blocks = []

    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [
                {"type": "text", "text": {"content": "📌 目录（TOC）"}}
            ]
        }
    })

    for stock in stocks.keys():
        blocks.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {
                        "type": "mention",
                        "mention": {"page": {"id": f"{stock}"}}
                    },
                    {"type": "text", "text": {"content": f"   ← 点击跳转到 {stock} 区块"}}
                ]
            }
        })
    return blocks


# -------------------------------------------------------
# 构建整个内容（目录 + 股票分区）
# -------------------------------------------------------
def build_page_blocks(stocks):
    blocks = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [
                {"type": "text", "text": {"content": f"📊 LP Monitor Dashboard ({now_str})"}}
            ]
        }
    })

    # -----------------------------
    # 添加目录部分
    # -----------------------------
    toc = build_toc_block(stocks)
    blocks.extend(toc)

    # -----------------------------
    # 添加每个股票的内容
    # -----------------------------
    for stock_name, png_list in stocks.items():

        # Heading anchor（用于 TOC 跳转）
        blocks.append({
            "object": "block",
            "id": stock_name,  # ⭐ 用 symbol 作为页面内部 anchor ID
            "type": "heading_2",
            "heading_2": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"📈 {stock_name}"}}
                ]
            }
        })

        for p in png_list:
            img_url = f"{BASE_URL}/{p['rel']}"

            blocks.append({
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": img_url}}
            })
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"🕒 Last updated: {p['mtime']}"}}
                    ]
                }
            })

    return blocks


# -------------------------------------------------------
# 推送到 Notion
# -------------------------------------------------------
def push_to_notion():
    token = os.getenv("NOTION_TOKEN")
    page_id = os.getenv("NOTION_PAGE_ID")
    if not token or not page_id:
        raise EnvironmentError("Missing NOTION_TOKEN or NOTION_PAGE_ID")

    cfg = load_config()
    output_dir = cfg.get("output_dir", "docs")

    stocks = get_stock_pngs(output_dir)
    if not stocks:
        print("[Warn] No PNG found.")
        return

    notion = Client(auth=token)

    # 清空页面
    existing = notion.blocks.children.list(page_id).get("results", [])
    for child in existing:
        try:
            notion.blocks.delete(child["id"])
        except:
            pass

    blocks = build_page_blocks(stocks)

    notion.blocks.children.append(page_id, children=blocks)

    print(f"[OK] Uploaded {sum(len(v) for v in stocks.values())} PNGs with TOC")


if __name__ == "__main__":
    push_to_notion()
