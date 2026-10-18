#!/usr/bin/env python3
"""figma_digest.py — token-cheap Figma reads via the REST API (stdlib only).

Design→code helper: the ClaudeTalkToFigma bridge returns huge JSON the model pays tokens for.
This fetches the file tree via REST, writes a COMPACT digest to disk, and optionally renders nodes
to PNG/SVG — so the model reads a few-KB digest + screenshot paths, never the MB tree. It is the
read-side complement to the bridge's write-side lib (place/export/tokens).

Reads only. The REST API has no design-mutation endpoints — writes stay on the plugin bridge.

Auth: a Figma personal access token (scope File content:read) in FIGMA_ACCESS_TOKEN (the var the
Code Connect wrapper also uses) or FIGMA_TOKEN, from the env or a gitignored .env / .env.local.

Usage:
  python3 figma_digest.py --file-key e64626df
  python3 figma_digest.py --file-key e64626df --ids 21011:3244 --depth 2
  python3 figma_digest.py --file-key e64626df --images 21011:3244,21016:61528 --format png --scale 2

Outputs (under --out, default design/figma/):
  digest.json         compact {nodeId: {name,type,w,h,x,y,fills[hex],text,componentId}}
  images/<id>.<fmt>   rendered nodes (only with --images)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.figma.com/v1"
TOKEN_VARS = ("FIGMA_ACCESS_TOKEN", "FIGMA_TOKEN")


def _token() -> str:
    for var in TOKEN_VARS:
        tok = os.environ.get(var, "").strip()
        if tok:
            return tok
    # fall back to a gitignored .env / .env.local in the repo root
    for env_path in (".env.local", ".env"):
        if os.path.isfile(env_path):
            with open(env_path) as f:
                for line in f:
                    for var in TOKEN_VARS:
                        if line.startswith(var + "="):
                            tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if tok:
                                return tok
    sys.exit(
        "error: set FIGMA_ACCESS_TOKEN (or FIGMA_TOKEN) — a Figma personal access token "
        "with File content:read, in the env or a gitignored .env.local"
    )


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Figma-Token": _token()})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"error: Figma API {e.code} on {path} — {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"error: network failure on {path} — {e}")


def _hex(color: dict) -> str:
    r, g, b = (round(color.get(k, 0) * 255) for k in ("r", "g", "b"))
    return f"#{r:02x}{g:02x}{b:02x}"


def _fills(node: dict) -> list[str]:
    out = []
    for p in node.get("fills", []) or []:
        if p.get("type") == "SOLID" and p.get("visible", True) and "color" in p:
            out.append(_hex(p["color"]))
    return out


def _digest_node(node: dict) -> dict:
    bb = node.get("absoluteBoundingBox") or {}
    d: dict = {"name": node.get("name"), "type": node.get("type")}
    if bb:
        d |= {"w": round(bb.get("width", 0)), "h": round(bb.get("height", 0)),
              "x": round(bb.get("x", 0)), "y": round(bb.get("y", 0))}
    f = _fills(node)
    if f:
        d["fills"] = f
    if node.get("type") == "TEXT" and node.get("characters"):
        d["text"] = node["characters"][:200]
    if node.get("componentId"):
        d["componentId"] = node["componentId"]
    return d


def _walk(node: dict, acc: dict) -> None:
    acc[node["id"]] = _digest_node(node)
    for child in node.get("children", []) or []:
        _walk(child, acc)


def _missing_ids(nodes: dict, requested: str) -> list[str]:
    """Requested ids the /nodes response returned null / without a document (deleted or wrong id).

    The endpoint returns HTTP 200 with `{"nodes": {"1:2": null}}` for a bad id, so these would
    otherwise be dropped silently and the digest just come back smaller.
    """
    return [i for i in (requested.split(",") if requested else [])
            if not ((nodes.get(i) or {}).get("document"))]


def _image_urls(img: dict, requested: str) -> dict:
    """Validated {id: url} from a /images response, failing LOUD on the HTTP-200 error cases.

    Figma's /images endpoint returns a top-level `err` (bad scale/format/unrenderable node) or an
    empty `images` map WITH HTTP 200 — so _get()'s HTTPError guard never fires and the caller would
    otherwise render nothing while reporting success.
    """
    if img.get("err"):
        sys.exit(f"error: Figma image render failed — {img['err']}")
    urls = img.get("images") or {}
    if not urls:
        sys.exit(f"error: no images returned for ids {requested}")
    return urls


def main() -> None:
    ap = argparse.ArgumentParser(description="Token-cheap Figma REST digest (reads only).")
    ap.add_argument("--file-key", required=True, help="Figma file key (from the file URL)")
    ap.add_argument("--ids", help="comma-separated node ids to scope the read (default: whole file)")
    ap.add_argument("--depth", type=int, help="tree depth (1=pages, 2=+top-level); omit for full")
    ap.add_argument("--out", default="design/figma", help="output dir (default design/figma)")
    ap.add_argument("--images", help="comma-separated node ids to render to image")
    ap.add_argument("--format", default="png", choices=["png", "svg", "jpg", "pdf"])
    ap.add_argument("--scale", type=float, default=2.0, help="image scale 0.01–4 (default 2)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # --- reads → compact digest -------------------------------------------------
    params: dict = {}
    if args.depth:
        params["depth"] = args.depth
    # NOTE: never request geometry=paths — vector data is what bloats the response.
    if args.ids:
        data = _get(f"/files/{args.file_key}/nodes", {**params, "ids": args.ids})
        nodes = data.get("nodes", {})
        missing = _missing_ids(nodes, args.ids)
        if missing:
            print(f"warning: no node returned for ids: {','.join(missing)}", file=sys.stderr)
        roots = [v["document"] for v in nodes.values() if v and v.get("document")]
    else:
        data = _get(f"/files/{args.file_key}", params)
        roots = [data["document"]] if data.get("document") else []

    acc: dict = {}
    for root in roots:
        _walk(root, acc)

    digest_path = os.path.join(args.out, "digest.json")
    with open(digest_path, "w") as f:
        json.dump(acc, f, indent=1)
    size_kb = os.path.getsize(digest_path) / 1024
    print(f"digest: {len(acc)} nodes → {digest_path} ({size_kb:.1f} KB)")

    # --- optional image render → download ---------------------------------------
    if args.images:
        img = _get(f"/images/{args.file_key}",
                   {"ids": args.images, "format": args.format, "scale": args.scale})
        urls = _image_urls(img, args.images)
        img_dir = os.path.join(args.out, "images")
        os.makedirs(img_dir, exist_ok=True)
        for node_id, url in urls.items():
            if not url:
                print(f"  image: {node_id} — no render returned (skipped)")
                continue
            dest = os.path.join(img_dir, f"{node_id.replace(':', '-')}.{args.format}")
            urllib.request.urlretrieve(url, dest)  # noqa: S310 (Figma CDN URL from the API)
            print(f"  image: {node_id} → {dest}")


if __name__ == "__main__":
    main()
