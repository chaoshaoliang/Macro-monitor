import os
import json
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")

# 初始化新版 SDK 的 Client
client = genai.Client(api_key=GEMINI_API_KEY)

def get_fred_latest(series_id):
    """從 FRED API 獲取最新一筆經濟數據"""
    if not FRED_API_KEY:
        print("⚠️ 警告：找不到 FRED_API_KEY，請檢查 GitHub Secrets！")
        return 0.0
        
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
    try:
        res = requests.get(url).json()
        if 'observations' in res:
            return float(res['observations'][0]['value'])
        else:
            print(f"FRED API 錯誤 ({series_id}): {res}") # 印出真實錯誤原因
            return 0.0
    except Exception as e:
        print(f"連線 FRED {series_id} 失敗: {e}")
        return 0.0

def get_yfinance_latest(ticker):
    """從 Yahoo Finance 獲取最新收盤價"""
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return round(data['Close'].iloc[-1], 2)
    except Exception as e:
        print(f"YF 抓取失敗 {ticker}: {e}")
        return 0.0

def scrape_cape():
    """爬取 multpl.com 的 Shiller PE Ratio"""
    try:
        # 加上偽裝 Header 避免被 GitHub Actions 的 IP 擋住 (403 Forbidden)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
        res = requests.get("https://www.multpl.com/shiller-pe", headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        cape_div = soup.find('div', id='bignum')
        if cape_div:
            return float(cape_div.text.strip().replace('\n', ''))
        else:
            print("找不到 CAPE 數據區塊。")
            return 36.6
    except Exception as e:
        print(f"CAPE 爬取失敗: {e}")
        return 36.6

def generate_ai_analysis(data_dict, prev_data=None):
    """呼叫 Gemini 進行分析 (使用新版 SDK)"""
    prev_str = f"昨日參考數據：10Y-2Y利差 {prev_data.get('t10y2yVal', 0)}%, HY OAS {prev_data.get('hyVal', 0)}%, VIX {prev_data.get('vixVal', 0)}。" if prev_data else ""
    
    prompt = f"""
    最新宏觀數據：
    AAA 10Y: {data_dict['igVal']}%, 10Y-2Y: {data_dict['t10y2yVal']}%, AAA OAS: {data_dict['aaaOasVal']}%, HY OAS: {data_dict['hyVal']}%,
    VIX: {data_dict['vixVal']}, CAPE: {data_dict['capeVal']}倍, VXN: {data_dict['vxnVal']}, CPI: {data_dict['cpiVal']}%, 
    美國10Y公債: {data_dict['t10yVal']}%, Brent原油: {data_dict['brentVal']}$。
    {prev_str}
    
    請依要求分大項並使用阿拉伯數字條列景氣解讀與具體理由。
    特別指示：
    1. 若VIX>30或極端恐慌，採取「左肩交易」策略，請給出具體的「分批資金控管」與「跌幅加碼級距」建議。
    2. 若VIX<15過度樂觀，說明「降槓桿」與獲利了結理由。
    3. 針對防禦部位，請說明配置「BOXX ETF」的理由。
    嚴禁使用 Markdown 符號。文字深黑。使用繁體中文。
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text.replace('**', '').replace('##', '').replace('*', '')
    except Exception as e:
        print(f"AI 生成失敗: {e}")
        return "AI 分析生成失敗，請檢查 API 狀態。"

def main():
    print("開始抓取數據...")
    new_data = {
        "igVal": get_fred_latest("AAA10Y"),
        "t10y2yVal": get_fred_latest("T10Y2Y"),
        "aaaOasVal": get_fred_latest("BAMLC0A1CAAA"),
        "hyVal": get_fred_latest("BAMLH0A0HYM2"),
        "ismVal": get_fred_latest("PMI"), 
        "vixVal": get_yfinance_latest("^VIX"),
        "vxnVal": get_yfinance_latest("^VXN"),
        "capeVal": scrape_cape(),
        "cpiVal": get_fred_latest("CPIAUCSL"),
        "t10yVal": get_fred_latest("DGS10"),
        "brentVal": get_yfinance_latest("BZ=F")
    }
    
    os.makedirs('data', exist_ok=True)
    
    # 讀取歷史資料 (加入防呆機制)
    history = []
    if os.path.exists('data/history.json'):
        with open('data/history.json', 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
                # 防呆：如果讀出來是字典 {}，強制轉為清單 []
                if isinstance(history, dict):
                    print("修正：history.json 格式錯誤 (dict)，已重置為 list。")
                    history = []
            except json.JSONDecodeError:
                history = []
                
    prev_data = history[0] if len(history) > 0 else None

    print("產生 AI 診斷分析...")
    new_data["aiContent"] = generate_ai_analysis(new_data, prev_data)
    new_data["timestamp"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    new_data["status"] = "自動追蹤"
    
    # 寫入最新資料
    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
        
    # 新增到歷史紀錄
    history.insert(0, new_data)
    history = history[:100] # 保留最新 100 筆
    
    with open('data/history.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        
    print("資料更新完成！")

if __name__ == "__main__":
    main()
