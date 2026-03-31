import os
import json
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from google import genai # 【重要更新】改用最新版 SDK
from datetime import datetime

# 環境變數設定
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")

def get_fred_latest(series_id):
    if not FRED_API_KEY:
        print("⚠️ 找不到 FRED_API_KEY")
        return 0.0
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
    try:
        res = requests.get(url).json()
        if 'observations' in res:
            return float(res['observations'][0]['value'])
        return 0.0
    except Exception as e:
        print(f"Error fetching FRED {series_id}: {e}")
        return 0.0

def get_yfinance_latest(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return round(data['Close'].iloc[-1], 2)
    except Exception as e:
        print(f"Error fetching YF {ticker}: {e}")
        return 0.0

def scrape_cape():
    try:
        headers = {'User-Agent': 'Mozilla/5.0'} # 加上 headers 避免被擋
        res = requests.get("https://www.multpl.com/shiller-pe", headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        cape_text = soup.find('div', id='bignum').text.strip().replace('\n', '')
        return float(cape_text)
    except Exception as e:
        print(f"Error fetching CAPE: {e}")
        return 36.6

# 判斷當前景氣狀態 (與前端邏輯同步)
def get_market_status(data):
    hy = data.get('hyVal', 0)
    yc = data.get('t10y2yVal', 0)
    ism = data.get('ismVal', 0)
    ig = data.get('igVal', 0)
    vix = data.get('vixVal', 0)
    vxn = data.get('vxnVal', 0)
    ao = data.get('aaaOasVal', 0)

    if hy >= 5.0 or yc < 0 or ism < 45 or ig >= 1.0 or vix >= 30 or vxn >= 32:
        return "極端風險"
    elif hy >= 3.5 or yc < 0.2 or ism < 50 or ig >= 0.7 or ao >= 0.5 or vix >= 20 or vxn >= 22:
        return "警戒狀態"
    elif vix > 0 and vix < 15:
        return "市場過熱"
    else:
        return "正常狀態"

# 判斷是否需要新增歷史紀錄
def should_record_history(curr_data, prev_data):
    if not prev_data: 
        return True
    
    if curr_data['status'] != prev_data.get('status', ''):
        return True

    thresholds = {
        'vixVal': 3.0, 'vxnVal': 3.0, 'hyVal': 0.2, 't10y2yVal': 0.15,
        'ismVal': 1.0, 't10yVal': 0.2, 'brentVal': 5.0, 'cpiVal': 0.2
    }

    for key, threshold in thresholds.items():
        curr_val = curr_data.get(key, 0)
        prev_val = prev_data.get(key, 0)
        if abs(curr_val - prev_val) >= threshold:
            print(f"指標大幅變動觸發紀錄: {key} 從 {prev_val} 變為 {curr_val} (差值 {abs(curr_val - prev_val):.2f})")
            return True
    return False

def generate_ai_analysis(data_dict, prev_data=None):
    if not GEMINI_API_KEY:
        return "⚠️ 未設定 Gemini API 金鑰"
        
    try:
        # 【重要更新】使用新版 SDK 呼叫方式
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        return f"⚠️ SDK 初始化失敗: {e}"

    prev_str = f"昨日參考數據：10Y-2Y利差 {prev_data.get('t10y2yVal', 0)}%, HY OAS {prev_data.get('hyVal', 0)}%, VIX {prev_data.get('vixVal', 0)}。" if prev_data else ""
    
    prompt = f"""
    最新宏觀數據：
    AAA 10Y: {data_dict['igVal']}%, 10Y-2Y: {data_dict['t10y2yVal']}%, AAA OAS: {data_dict['aaaOasVal']}%, HY OAS: {data_dict['hyVal']}%,
    VIX: {data_dict['vixVal']}, CAPE: {data_dict['capeVal']}倍, VXN: {data_dict['vxnVal']}, CPI: {data_dict['cpiVal']}%, 
    美國10Y公債: {data_dict['t10yVal']}%, Brent原油: {data_dict['brentVal']}$。
    系統判定狀態：{data_dict['status']}
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
        print(f"AI Generation Error: {e}")
        return f"AI 分析生成失敗，錯誤代碼：{str(e)}"

def main():
    print("Fetching data...")
    new_data = {
        "igVal": get_fred_latest("AAA10Y"), "t10y2yVal": get_fred_latest("T10Y2Y"),
        "aaaOasVal": get_fred_latest("BAMLC0A1CAAA"), "hyVal": get_fred_latest("BAMLH0A0HYM2"),
        "ismVal": get_fred_latest("PMI"), "vixVal": get_yfinance_latest("^VIX"),
        "vxnVal": get_yfinance_latest("^VXN"), "capeVal": scrape_cape(),
        "cpiVal": get_fred_latest("CPIAUCSL"), "t10yVal": get_fred_latest("DGS10"),
        "brentVal": get_yfinance_latest("BZ=F")
    }
    
    new_data["status"] = get_market_status(new_data)
    os.makedirs('data', exist_ok=True)
    
    history = []
    if os.path.exists('data/history.json'):
        with open('data/history.json', 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
                if isinstance(history, dict): history = []
            except json.JSONDecodeError:
                history = []
                
    prev_data = history[0] if len(history) > 0 else None

    print(f"Current Status: {new_data['status']}")
    print("Generating AI Analysis...")
    ai_content = generate_ai_analysis(new_data, prev_data)
    
    new_data["aiContent"] = ai_content
    new_data["timestamp"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    
    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
        
    if should_record_history(new_data, prev_data):
        print("檢測到顯著變動，正在將數據寫入歷史紀錄...")
        history.insert(0, new_data)
        history = history[:100]
        with open('data/history.json', 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    else:
        print("指標無顯著變動，今日不新增歷史紀錄。")
        
    # 將狀態輸出給 GitHub Action 以利觸發 Email 告警
    is_alert = "正常" not in new_data["status"]
    github_output = os.getenv('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"is_alert={str(is_alert).lower()}\n")
            f.write(f"status={new_data['status']}\n")
            
    print("Update complete!")

if __name__ == "__main__":
    main()
