#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Push LP Monitor PNGs to Notion Page (CDN Version)
------------------------------------------------
- Reads stocks from config.yaml (no secrets inside)
- Reads NOTION_TOKEN / NOTION_PAGE_ID from env vars
- BASE_URL is now FIXED to jsDelivr CDN (no more RAW issues)
- Pushes PNGs under docs/ to Notion page
"""

import os, yaml, json, time
from datetime import datetime
from notion_client import Client

# -------------------------------------------------------
# ✅ BASE_URL 直接固定为 jsDelivr CDN，不再依赖环境变量
# -------------------------------------------------------
BASE_URL = "https://cdn.jsdelivr.net/gh/CMUJIN/liquidity-premium-monitor@main/docs"


def load_config(path="config.yaml"):
    if not os.path.exists(path):
        raise FileNotFoundError("Missing config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_png_files(base_dir):
    pngs = []
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.endswith(".png"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, base_dir)
                mtime = os.path.getmtime(full)
                pngs.append({
                    "path": full,
                    "rel": rel.replace("\\", "/"),
                    "mtime": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                })
    return sorted(pngs, key=lambda x: x["rel"])


def build_image_blocks(pngs):
    blocks = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [
                {"type": "text", "text": {"content": f"📊 LP Monitor Update ({now_str})"}}
            ]
        }
    })

    for p in pngs:
        # -------------------------------------------------------
        # ✅ 使用 CDN，不加 ?v 参数，避免 Notion 无法加载
        # -------------------------------------------------------
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


def push_to_notion():
    # -------------------------------------------------------
    # NOTION_TOKEN / NOTION_PAGE_ID 仍然从环境变量读取
    # -------------------------------------------------------
    token = os.getenv("NOTION_TOKEN")
    page_id = os.getenv("NOTION_PAGE_ID")

    if not token or not page_id:
        raise EnvironmentError("Missing environment variables: NOTION_TOKEN / NOTION_PAGE_ID")

    cfg = load_config()
    output_dir = cfg.get("output_dir", "docs")

    pngs = get_png_files(output_dir)
    if not pngs:
        print("[Warn] No PNG files found.")
        return

    notion = Client(auth=token)
    blocks = build_image_blocks(pngs)

    # 清空旧内容
    existing = notion.blocks.children.list(page_id).get("results", [])
    for child in existing:
        try:
            notion.blocks.delete(child["id"])
        except Exception as e:
            print(f"[Warn] Could not delete block: {e}")

    # 写入 Notion
    notion.blocks.children.append(block_id=page_id, children=blocks)

    print(f"[Done] Uploaded {len(pngs)} images to Notion at {datetime.now()}")


if __name__ == "__main__":
    push_to_notion()
