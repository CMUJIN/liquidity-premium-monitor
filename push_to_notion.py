#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Push LP Monitor PNGs to Notion Page (Safe for Public Repos)
------------------------------------------------------------
- Reads stocks from config.yaml (no secrets inside)
- Reads NOTION_TOKEN / NOTION_PAGE_ID / BASE_URL from env vars
- Pushes PNGs under docs/ to Notion page
- Appends ?v=<timestamp> to image URLs to avoid caching
"""

import os, yaml, json, time
from datetime import datetime
from notion_client import Client

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

def build_image_blocks(pngs, base_url):
    blocks = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"📊 LP Monitor Update ({now_str})"}}]}
    })

    for p in pngs:
        img_url = f"{base_url}/{p['rel']}?v={int(time.time())}"
        blocks.append({
            "object": "block",
            "type": "image",
            "image": {"type": "external", "external": {"url": img_url}}
        })
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🕒 Last updated: {p['mtime']}"}}]}
        })
    return blocks

def push_to_notion():
    # 从环境变量读取
    token = os.getenv("NOTION_TOKEN")
    page_id = os.getenv("NOTION_PAGE_ID")
    base_url = os.getenv("BASE_URL")

    if not token or not page_id or not base_url:
        raise EnvironmentError("Missing environment variables: NOTION_TOKEN / NOTION_PAGE_ID / BASE_URL")

    cfg = load_config()
    output_dir = cfg.get("output_dir", "docs")

    pngs = get_png_files(output_dir)
    if not pngs:
        print("[Warn] No PNG files found.")
        return

    notion = Client(auth=token)
    blocks = build_image_blocks(pngs, base_url)

    # 清空旧内容
    children = notion.blocks.children.list(page_id).get("results", [])
    for child in children:
        notion.blocks.delete(child["id"])

    # 推送新内容
    notion.blocks.children.append(page_id, {"children": blocks})
    print(f"[Done] Uploaded {len(pngs)} images to Notion at {datetime.now()}")

if __name__ == "__main__":
    push_to_notion()
