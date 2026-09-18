"""
获取 A 股大盘数据（上证指数、沪深300、创业板指、上证50、中证500、中证1000、科创50）
独立脚本，供 Skill 和其他分析流程调用

用法:
  python scripts/utils/fetch_market_data.py               # 默认2026年全年
  python scripts/utils/fetch_market_data.py --start 20250101    # 指定起始日期
  python scripts/utils/fetch_market_data.py --start 20240601    # 全量刷新（Direction 前置要求）

与已有 market_data.json 合并写回：仅替换 [start, end] 区间内的行，
区间外的旧数据和其他指数的数据保留，不会整文件覆盖。
"""

import json
import os
import argparse
from datetime import datetime
import pandas as pd
import akshare as ak

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "market")
os.makedirs(DATA_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(DATA_DIR, "market_data.json")

# 7 大指数（与 SKILL.md §2 的 key 一一对应）
INDICES = [
    ("sh000001", "上证指数"),
    ("sh000300", "沪深300"),
    ("sz399006", "创业板指"),
    ("sh000016", "上证50"),
    ("sh000905", "中证500"),
    ("sh000852", "中证1000"),
    ("sh000688", "科创50"),
]


def fetch_index(symbol, name, start_date, end_date, verbose=True):
    """获取单个指数的日线数据"""
    if verbose:
        print(f"  获取{name} ({symbol})...")
    try:
        df = ak.stock_zh_index_daily_em(symbol=symbol, start_date=start_date, end_date=end_date)
        df = df.rename(columns={
            "date": "日期", "open": "开盘", "close": "收盘",
            "high": "最高", "low": "最低", "volume": "成交量",
        })
        # 保留成交量字段（上证有），其他指数可能没有则删
        keep_cols = ["日期", "开盘", "收盘", "最高", "最低"]
        if "成交量" in df.columns:
            keep_cols.append("成交量")
        df = df[keep_cols]
        if verbose:
            print(f"    {len(df)} 条记录")
        return df
    except Exception as e:
        if verbose:
            print(f"    ❌ 失败: {e}")
        return None


def iso_date(compact):
    """YYYYMMDD -> YYYY-MM-DD"""
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


def refresh(start=None, end=None, verbose=True):
    """抓 [start, end] 区间日线，与已有文件合并写回（区间外的旧行与其他指数保留）。

    手动 CLI（main）与推送链起档（briefing.market.refresh_history）共用这一份。
    返回 (抓到新行的指数名, 抓取失败的指数名)；全部指数都失败 → 不写盘，返回 ([], 全部)。
    """
    start = start or "20260101"
    end = end or datetime.now().strftime("%Y%m%d")
    start_iso, end_iso = iso_date(start), iso_date(end)

    if verbose:
        print(f"获取 {start} ~ {end} 大盘数据...")

    # 读取旧文件，保留未重新抓取的指数与区间外的旧行
    old = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                old = json.load(f)
            if verbose:
                print(f"已读取旧数据: {', '.join(old.keys())}")
        except Exception as e:
            if verbose:
                print(f"旧数据读取失败（将全量重建）: {e}")

    result = dict(old)
    ok, failed = [], []
    for symbol, name in INDICES:
        df = fetch_index(symbol, name, start, end, verbose=verbose)
        if df is None:
            if verbose:
                print(f"  ⚠️ {name} 获取失败，保留旧数据")
            failed.append(name)
            continue
        new_rows = df.to_dict(orient="records")
        old_rows = [
            r for r in old.get(name, [])
            if not (start_iso <= r["日期"] <= end_iso)
        ]
        merged = {}
        for r in old_rows + new_rows:
            merged[r["日期"]] = r  # 按日期去重，新行覆盖旧行
        result[name] = [merged[d] for d in sorted(merged)]
        if new_rows:
            ok.append(name)

    if not result:
        if verbose:
            print("❌ 所有指数获取失败")
        return [], failed

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"\n✅ 已保存: {OUTPUT_FILE}")
        for name, rows in result.items():
            print(f"  {name}: {len(rows)} 条（{rows[0]['日期']} ~ {rows[-1]['日期']}）")
    return ok, failed


def main():
    parser = argparse.ArgumentParser(description="获取A股大盘数据")
    parser.add_argument("--start", default=None, help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD")
    args = parser.parse_args()
    refresh(args.start, args.end)


if __name__ == "__main__":
    main()
