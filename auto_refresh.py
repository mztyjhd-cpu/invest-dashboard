#!/usr/bin/env python3
"""
仪表盘自动刷新脚本
每小时运行一次：抓行情 + 搜微博 → 更新 data.json → 推送
触发方式：GitHub Actions 定时 / 手动运行
"""
import json, re, os, subprocess
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote

DATA_FILE = os.path.join(os.path.dirname(__file__), 'data.json')

def fetch(url, encoding='utf-8'):
    """带UA的GET请求"""
    req = Request(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'})
    with urlopen(req, timeout=15) as r:
        return r.read().decode(encoding, errors='replace')

def get_markets():
    """从东方财富获取15个全球指数"""
    ids = ['1.000001','0.399001','1.000688','0.399006','1.000300','1.000905',
           '100.HSI','100.NDX','100.SPX','100.DJI','100.N225',
           '113.GOLD','113.WTI']
    names = {'1.000001':'上证指数','0.399001':'深证成指','1.000688':'科创50',
             '0.399006':'创业板指','1.000300':'沪深300','1.000905':'中证500',
             '100.HSI':'恒生指数','100.NDX':'纳斯达克','100.SPX':'标普500',
             '100.DJI':'道琼斯','100.N225':'日经225','113.GOLD':'现货黄金','113.WTI':'WTI原油'}
    url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f12,f14&secids={','.join(ids)}"
    try:
        data = json.loads(fetch(url))
        results = []
        for item in data.get('data',{}).get('diff',[]):
            code = item['f12']
            name = names.get(f"1.{code}") or names.get(f"0.{code}") or names.get(f"100.{code}") or item.get('f14','')
            price = item.get('f2',0)
            chg = item.get('f3',0)
            chg_amt = item.get('f4',0)
            results.append({
                "name": name, "price": f"{price:.2f}",
                "chg": f"{chg_amt:+.2f}", "chgp": f"{chg:+.2f}%"
            })
        return results
    except Exception as e:
        print(f"Market fetch failed: {e}")
        return []

def search_weibo(keyword, count=3):
    """搜索微博（简化版，搜关键词+最近时间）"""
    # 使用新浪搜索API（有限制，但免费）
    results = []
    try:
        url = f"https://s.weibo.com/weibo?q={quote(keyword)}&typeall=1&suball=1&timescope=custom:{(datetime.now().strftime('%Y-%m-%d'))}:{(datetime.now().strftime('%Y-%m-%d'))}&Refer=g"
        html = fetch(url)
        # 简单提取微博文本（实际生产环境需要更robust的解析）
        cards = re.findall(r'<p[^>]*node-type="feed_list_content"[^>]*>(.*?)</p>', html, re.DOTALL)
        for i, card in enumerate(cards[:count]):
            text = re.sub(r'<[^>]+>', '', card).strip()
            if text and len(text) > 10:
                results.append(text)
    except Exception as e:
        print(f"Weibo search failed for {keyword}: {e}")
    return results

def classify_post(text, blogger):
    """分类微博内容（山人/猫大几乎全是财经内容，极少量过滤）"""
    text_lower = text.lower()
    # 只排除非常明显与投资无关的纯日常内容
    pure_daily = ['发自拍','生日快乐','新年快乐','拜年','抽奖','红包','广告']
    if any(w in text for w in pure_daily):
        return None
    # 确定标签
    if any(w in text for w in ['纳指','纳科','溢价','打野','做踢','T+0','ETF','道琼斯','标普','QDII','美股','英伟达']):
        return '操作策略'
    if any(w in text for w in ['半年线','梭哈','共振','反弹','支撑','底部','顶部','金针','金叉','死叉','MACD','RSI']):
        return '中期判断'
    if any(w in text for w in ['仓位','封仓','滚动','加仓','减仓','补仓','子弹','层','计划']):
        return '仓位管理'
    if any(w in text for w in ['半导体','锂电','光伏','风电','军工','银行','消费','医疗','白酒','煤炭','抱团','轮动','涨停','跌停','连板','趋势','龙头']):
        return '板块分析'
    if any(w in text for w in ['中枢','结构','背驰','背离','5分钟','30分钟','日线','周线','头肩','突破','支撑位','压力位']):
        return '结构分析'
    if any(w in text for w in ['效率','共识','预期','人声鼎沸','流动性','风偏']):
        return '效率判断'
    if any(w in text for w in ['A股','大盘','指数','个股','盘面','收盘','开盘','跳水','拉升','翻红','翻绿']):
        return '市场观点'
    return '市场观点'

def update_live_posts(data):
    """更新山人和猫大的实时观点"""
    now = datetime.now()
    time_str = now.strftime('%m-%d %H:%M')

    # 山人
    posts = search_weibo('山人I ETF 纳指', 6)
    finance_posts = []
    for p in posts:
        tag = classify_post(p, 'shanren')
        if tag:
            finance_posts.append({"time": time_str, "text": p[:200], "tag": tag})
        if len(finance_posts) >= 3:
            break
    if finance_posts:
        data['bloggers']['shanren']['live_posts'] = finance_posts

    # 猫大
    posts = search_weibo('让我赚点钱买个猫吧 A股', 6)
    finance_posts = []
    for p in posts:
        tag = classify_post(p, 'maoda')
        if tag:
            finance_posts.append({"time": time_str, "text": p[:200], "tag": tag})
        if len(finance_posts) >= 3:
            break
    if finance_posts:
        data['bloggers']['maoda']['live_posts'] = finance_posts

    return data

def main():
    print(f"[{datetime.now()}] 自动刷新仪表盘...")

    # 加载现有数据
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 更新行情
    markets = get_markets()
    if markets:
        data['markets'] = markets
        print(f"  ✅ 行情: {len(markets)} 个指数")

    # 更新微博
    data = update_live_posts(data)
    print(f"  ✅ 微博: 已更新")

    # 更新时间
    data['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 写回
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Git 提交推送
    try:
        subprocess.run(['git', 'config', 'user.name', 'dashboard-bot'], check=True)
        subprocess.run(['git', 'config', 'user.email', 'bot@dashboard.local'], check=True)
        subprocess.run(['git', 'add', 'data.json'], check=True)
        subprocess.run(['git', 'commit', '-m', f'自动刷新 {datetime.now().strftime("%m-%d %H:%M")}'], check=True)
        subprocess.run(['git', 'push'], check=True)
        print(f"  ✅ 已推送")
    except Exception as e:
        print(f"  ⚠️ 推送失败: {e}")

if __name__ == '__main__':
    main()
