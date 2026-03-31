import os
import json
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime

# 讀取環境變數 (請確保 GitHub Secrets 有正確設定)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")

def get_fred_latest(series_id):
    """從 FRED API 獲取最新一筆經濟數據"""
    if not FRED_API_KEY:
        return 0.0
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
    try:
        res = requests.get(url).json()
        if 'observations' in res:
            return float(res['observations'][0]['value'])
        return 0.0
    except Exception:
        return 0.0

def get_yfinance_latest(ticker):
    """從 Yahoo Finance 獲取最新收盤價"""
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return round(data['Close'].iloc[-1], 2)
    except Exception:
        return 0.0

def scrape_cape():
    """爬取 multpl.com 的 Shiller PE Ratio"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get("https://www.multpl.com/shiller-pe", headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        cape_div = soup.find('div', id='bignum')
        if cape_div:
            return float(cape_div.text.strip().replace('\n', ''))
        return 36.6
    except Exception:
        return 36.6

def calculate_market_status(d):
    """根據數據自動計算當前市場狀態 (與前端邏輯同步)"""
    if d['hyVal'] >= 5.0 or d['t10y2yVal'] < 0 or d['ismVal'] < 45 or d['igVal'] >= 1.0 or d['vixVal'] >= 30 or d['vxnVal'] >= 32:
        return "極端風險"
    elif d['hyVal'] >= 3.5 or d['t10y2yVal'] < 0.2 or d['ismVal'] < 50 or d['igVal'] >= 0.7 or d['aaaOasVal'] >= 0.5 or d['vixVal'] >= 20 or d['vxnVal'] >= 22:
        return "警戒狀態"
    elif d['vixVal'] > 0 and d['vixVal'] < 15:
        return "市場過熱"
    else:
        return "正常狀態"

def generate_ai_analysis(data_dict, prev_data=None):
    """呼叫 Gemini 進行分析"""
    if not GEMINI_API_KEY:
        return "⚠️ Gemini API Key 未設定，無法呼叫 AI 生成報告。請檢查 GitHub Secrets。"

    # 初始化新版 SDK 的 Client
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        return f"⚠️ SDK 初始化失敗: {e}"

    prev_str = f"昨日參考數據：10Y-2Y利差 {prev_data.get('t10y2yVal', 0)}%, HY OAS {prev_data.get('hyVal', 0)}%, VIX {prev_data.get('vixVal', 0)}。" if prev_data else ""
    
    prompt = f"""
    最新宏觀數據：
    AAA 10Y: {data_dict['igVal']}%, 10Y-2Y: {data_dict['t10y2yVal']}%, AAA OAS: {data_dict['aaaOasVal']}%, HY OAS: {data_dict['hyVal']}%,
    VIX: {data_dict['vixVal']}, CAPE: {data_dict['capeVal']}倍, VXN: {data_dict['vxnVal']}, CPI: {data_dict['cpiVal']}%, 
    美國10Y公債: {data_dict['t10yVal']}%, Brent原油: {data_dict['brentVal']}$。
    當前系統判定狀態為：{data_dict['status']}
    {prev_str}
    
    請以專業華爾街分析師的角度，依要求分大項並使用阿拉伯數字條列景氣解讀與具體理由。
    特別指示：
    1. 若VIX>30或極端恐慌，採取「左肩交易」策略，請給出具體的「分批資金控管」與「跌幅加碼級距」建議。
    2. 若VIX<15過度樂觀，說明「降槓桿」與獲利了結理由。
    3. 針對防禦部位，請說明配置「BOXX ETF」的理由(約4.5%年化無風險利率、淨值穩定無減損)。
    嚴禁使用 Markdown 符號。文字深黑。使用繁體中文。
    """
    
    try:
        # 使用官方最新的穩定版模型
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        if response.text:
            return response.text.replace('**', '').replace('##', '').replace('*', '')
        else:
            return "⚠️ AI 回傳了空白內容，可能遭到安全機制阻擋。"
    except Exception as e:
        print(f"AI 生成失敗: {e}")
        return f"⚠️ 呼叫 Gemini API 失敗，錯誤代碼：\n{str(e)}"

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
    
    # 計算並寫入當前狀態 (重要！讓 Email 能知道真實狀態)
    new_data["status"] = calculate_market_status(new_data)
    
    os.makedirs('data', exist_ok=True)
    
    # 讀取歷史資料
    history = []
    if os.path.exists('data/history.json'):
        with open('data/history.json', 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
                if isinstance(history, dict): history = []
            except Exception:
                history = []
                
    prev_data = history[0] if len(history) > 0 else None

    print(f"當前狀態: {new_data['status']}，產生 AI 診斷分析...")
    new_data["aiContent"] = generate_ai_analysis(new_data, prev_data)
    new_data["timestamp"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    
    # 寫入最新資料
    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
        
    # 新增到歷史紀錄
    history.insert(0, new_data)
    history = history[:100] 
    
    with open('data/history.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        
    # --- GitHub Actions 變數輸出 (發送 Email 用) ---
    is_alert = "正常" not in new_data["status"]
    github_output = os.getenv('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"is_alert={str(is_alert).lower()}\n")
            f.write(f"status={new_data['status']}\n")
            
    print("資料更新完成！")

if __name__ == "__main__":
    main()

