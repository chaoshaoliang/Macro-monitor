import os
import json
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from google import genai # 引入全新的 Google GenAI SDK
from datetime import datetime

# 環境變數設定
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")

# 初始化新版 SDK 的 Client
client = genai.Client(api_key=GEMINI_API_KEY)

def get_fred_latest(series_id):
    """從 FRED API 獲取最新一筆經濟數據"""
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
    try:
        res = requests.get(url).json()
        return float(res['observations'][0]['value'])
    except Exception as e:
        print(f"Error fetching FRED {series_id}: {e}")
        return 0.0

def get_yfinance_latest(ticker):
    """從 Yahoo Finance 獲取最新收盤價"""
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return round(data['Close'].iloc[-1], 2)
    except Exception as e:
        print(f"Error fetching YF {ticker}: {e}")
        return 0.0

def scrape_cape():
    """爬取 multpl.com 的 Shiller PE Ratio"""
    try:
        res = requests.get("https://www.multpl.com/shiller-pe", headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(res.text, 'html.parser')
        cape_text = soup.find('div', id='bignum').text.strip().replace('\n', '')
        return float(cape_text)
    except Exception as e:
        print(f"Error fetching CAPE: {e}")
        return 36.6 # 發生錯誤時的預設值

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
        # 使用新版 SDK 的呼叫方式
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text.replace('**', '').replace('##', '').replace('*', '')
    except Exception as e:
        print(f"AI Generation Error: {e}")
        return "AI 分析生成失敗，請檢查 API 狀態。"

def main():
    print("Fetching data...")
    # 抓取數據
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
    
    # 建立目錄
    os.makedirs('data', exist_ok=True)
    
    # 讀取歷史資料以供 AI 參考
    history = []
    if os.path.exists('data/history.json'):
        with open('data/history.json', 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
                
    prev_data = history[0] if len(history) > 0 else None

    print("Generating AI Analysis...")
    ai_content = generate_ai_analysis(new_data, prev_data)
    
    new_data["aiContent"] = ai_content
    new_data["timestamp"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    new_data["status"] = "系統自動更新"
    
    # 寫入最新資料
    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
        
    # 新增到歷史紀錄 (保留最近 100 筆即可)
    history.insert(0, new_data)
    history = history[:100]
    
    with open('data/history.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        
    print("Update complete!")

if __name__ == "__main__":
    main()
