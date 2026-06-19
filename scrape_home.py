#!/usr/bin/env python3
"""GitHub Actions Playwright 首页饰品指数抓取脚本

在 GA runner 内运行，用 Playwright 抓取 CSQAQ 首页饰品指数 K 线和各类指标数据。
输出 home_result.json。

数据来源：
1. GET /proxies/api/v1/current_data — 所有指数当前值 + 武器类型涨跌 + 其他指标
2. GET /proxies/api/v1/sub_data?id={id}&type={type} — 指数 K 线历史（daily/hours）

用法：
  python scrape_home.py
  python scrape_home.py --indices 1,2,7,8  # 只抓指定指数
  python scrape_home.py --periods daily,hours  # 只抓指定周期
"""

import argparse
import json
import datetime
from playwright.sync_api import sync_playwright

HOME_URL = "https://csqaq.com/home"
RESULT_FILE = "home_result.json"

# 默认抓取的指数 ID（从 current_data 的 sub_index_data 获取）
# id -> (name, name_key)
DEFAULT_INDEX_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]

# 默认抓取的周期
DEFAULT_PERIODS = ["daily", "hours"]

# 指数名称映射（用于点击切换）
INDEX_NAME_MAP = {
    1: "饰品指数", 2: "租赁指数", 3: "百元主战", 4: "探员指数", 5: "原皮指数",
    6: "贴纸指数", 7: "匕首指数", 8: "手套指数", 9: "挂件指数", 10: "音乐盒",
    11: "2023巴黎", 12: "2024哥本", 14: "2024上海", 15: "武库指数", 16: "千战指数",
    17: "2025奥斯汀", 18: "一代手套", 19: "二代手套", 20: "三代手套",
    21: "收藏品", 22: "多普勒", 23: "伽玛多普勒", 24: "红皮指数",
}

# 周期切换按钮文本映射
PERIOD_BUTTON_MAP = {
    "daily": "日线",
    "hours": "时线",
}


def scrape_home(page, index_ids, periods):
    """抓取首页数据"""
    print(f"\n{'='*60}", flush=True)
    print(f"  抓取 CSQAQ 首页饰品指数数据", flush=True)
    print(f"  指数: {index_ids}", flush=True)
    print(f"  周期: {periods}", flush=True)
    print(f"{'='*60}", flush=True)

    result = {
        "scrape_time": datetime.datetime.now().isoformat(),
        "home_url": HOME_URL,
        "current_data": None,
        "sub_data": {},  # {index_id: {period: data}}
        "scrape_ok": False,
        "scrape_fail": "",
    }

    # 拦截 API 响应
    api_data = {
        "current_data": None,
        "sub_data": {},  # {(id, type): data}
    }

    def handle_response(response):
        url = response.url
        if "csqaq.com/proxies/api" not in url:
            return
        try:
            body = response.text()
            if not body or len(body) > 5000000:
                return

            # current_data 接口
            if "current_data" in url:
                parsed = json.loads(body)
                if parsed.get("code") == 200 and parsed.get("data"):
                    api_data["current_data"] = parsed["data"]
                    print(f"  [拦截] current_data: {len(body)} bytes", flush=True)
                return

            # sub_data 接口
            if "sub_data" in url:
                parsed = json.loads(body)
                if parsed.get("code") == 200 and parsed.get("data"):
                    # 解析 url 参数 id 和 type
                    import urllib.parse
                    parsed_url = urllib.parse.urlparse(url)
                    params = urllib.parse.parse_qs(parsed_url.query)
                    idx_id = int(params.get("id", [0])[0])
                    idx_type = params.get("type", [""])[0]
                    if idx_id and idx_type:
                        api_data["sub_data"][(idx_id, idx_type)] = parsed["data"]
                        print(f"  [拦截] sub_data id={idx_id} type={idx_type}: {len(body)} bytes", flush=True)
                return
        except Exception as e:
            print(f"  [拦截异常] {type(e).__name__}: {e}", flush=True)

    page.on("response", handle_response)

    try:
        # 1. 访问首页
        print(f"\n[1] 访问首页...", flush=True)
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(8000)
        print(f"  首页加载完成", flush=True)

        # 2. 等待 current_data 加载
        print(f"\n[2] 等待 current_data 加载...", flush=True)
        if api_data["current_data"]:
            sub_count = len(api_data["current_data"].get("sub_index_data", []))
            chg_count = len(api_data["current_data"].get("chg_type_data", []))
            print(f"  ✓ current_data: {sub_count} 个指数, {chg_count} 个武器类型", flush=True)
        else:
            print(f"  ✗ current_data 未加载", flush=True)

        # 3. 抓取所有指数的 K 线数据
        print(f"\n[3] 抓取所有指数的 K 线数据...", flush=True)
        for idx_id in index_ids:
            idx_name = INDEX_NAME_MAP.get(idx_id, f"id={idx_id}")
            for period in periods:
                # 检查是否已有该数据
                if (idx_id, period) in api_data["sub_data"]:
                    print(f"  ✓ {idx_name}({idx_id}) {period}: 已有数据", flush=True)
                    continue

                # 点击指数名称切换
                print(f"  点击 {idx_name}({idx_id})...", flush=True)
                clicked = page.evaluate(f"""() => {{
                    const allElements = document.querySelectorAll('*');
                    for (const el of allElements) {{
                        if (el.textContent.trim() === '{idx_name}' && el.offsetParent !== null && el.children.length === 0) {{
                            el.click();
                            return true;
                        }}
                    }}
                    return false;
                }}""")
                if not clicked:
                    print(f"    ✗ 未找到 {idx_name} 按钮", flush=True)
                    continue
                page.wait_for_timeout(2000)

                # 切换周期
                period_btn = PERIOD_BUTTON_MAP.get(period)
                if period_btn:
                    print(f"    切换周期到 {period_btn}...", flush=True)
                    page.evaluate(f"""() => {{
                        const els = document.querySelectorAll('.ant-segmented-item-label, span, div');
                        for (const el of els) {{
                            if (el.textContent.trim() === '{period_btn}' && el.offsetParent !== null) {{
                                el.click();
                                return true;
                            }}
                        }}
                        return false;
                    }}""")
                    page.wait_for_timeout(3000)

                # 检查是否获取到数据
                if (idx_id, period) in api_data["sub_data"]:
                    data = api_data["sub_data"][(idx_id, period)]
                    ts_count = len(data.get("timestamp", []))
                    print(f"    ✓ {idx_name} {period}: {ts_count} 条", flush=True)
                else:
                    print(f"    ✗ {idx_name} {period}: 未获取到数据", flush=True)

        # 4. 整理结果
        print(f"\n[4] 整理结果...", flush=True)
        result["current_data"] = api_data["current_data"]

        for idx_id in index_ids:
            idx_name = INDEX_NAME_MAP.get(idx_id, f"id={idx_id}")
            result["sub_data"][str(idx_id)] = {
                "name": idx_name,
                "id": idx_id,
                "periods": {},
            }
            for period in periods:
                if (idx_id, period) in api_data["sub_data"]:
                    result["sub_data"][str(idx_id)]["periods"][period] = api_data["sub_data"][(idx_id, period)]

        # 标记成功
        if result["current_data"]:
            result["scrape_ok"] = True
        else:
            result["scrape_fail"] = "无 current_data"

    except Exception as e:
        result["scrape_fail"] = f"{type(e).__name__}: {e}"
        print(f"  [ERROR] {type(e).__name__}: {e}", flush=True)

    page.remove_listener("response", handle_response)
    return result


def main():
    parser = argparse.ArgumentParser(description="CSQAQ 首页饰品指数抓取")
    parser.add_argument("--indices", default="", help="逗号分隔的指数 ID（默认全部）")
    parser.add_argument("--periods", default="", help="逗号分隔的周期（默认 daily,hours）")
    args = parser.parse_args()

    print("=" * 60, flush=True)
    print("  CSQAQ 首页饰品指数 Playwright 抓取", flush=True)
    print("=" * 60, flush=True)

    # 解析参数
    if args.indices:
        index_ids = [int(x.strip()) for x in args.indices.split(",") if x.strip()]
    else:
        index_ids = DEFAULT_INDEX_IDS

    if args.periods:
        periods = [x.strip() for x in args.periods.split(",") if x.strip()]
    else:
        periods = DEFAULT_PERIODS

    print(f"  指数: {index_ids}", flush=True)
    print(f"  周期: {periods}", flush=True)

    start_time = datetime.datetime.now()

    result = {
        "version": "v1",
        "start_time": start_time.isoformat(),
        "home_url": HOME_URL,
        "indices": index_ids,
        "periods": periods,
        "data": None,
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                viewport={"width": 1400, "height": 900},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="zh-CN",
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            scrape_result = scrape_home(page, index_ids, periods)
            result["data"] = scrape_result

            browser.close()

    except Exception as e:
        print(f"\n[FATAL] {type(e).__name__}: {e}", flush=True)
        result["data"] = {
            "scrape_ok": False,
            "scrape_fail": f"FATAL: {type(e).__name__}: {e}",
        }

    end_time = datetime.datetime.now()
    result["end_time"] = end_time.isoformat()
    result["total_duration_seconds"] = (end_time - start_time).total_seconds()

    # 保存结果
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    # 汇总
    print(f"\n{'='*60}", flush=True)
    print(f"  汇总", flush=True)
    print(f"{'='*60}", flush=True)
    if result["data"]:
        ok = "✓" if result["data"].get("scrape_ok") else "✗"
        print(f"  状态: {ok} {result['data'].get('scrape_fail', '')}", flush=True)
        if result["data"].get("current_data"):
            cd = result["data"]["current_data"]
            print(f"  current_data: {len(cd.get('sub_index_data', []))} 个指数, "
                  f"{len(cd.get('chg_type_data', []))} 个武器类型", flush=True)
        sub_data = result["data"].get("sub_data", {})
        total_kline = 0
        for idx_id, info in sub_data.items():
            for period, data in info.get("periods", {}).items():
                ts_count = len(data.get("timestamp", []))
                total_kline += ts_count
                print(f"  sub_data id={idx_id}({info['name']}) {period}: {ts_count} 条", flush=True)
        print(f"  K线总条数: {total_kline}", flush=True)
    print(f"  耗时: {result['total_duration_seconds']:.0f}s", flush=True)
    print(f"  结果: {RESULT_FILE}", flush=True)


if __name__ == "__main__":
    main()
