 import os
import json
import requests
import yfinance as yf
import gspread
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 環境變數與設定
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")
# 請在 GitHub Secrets 新增此項，放您的 Google Sheet CSV 網址或試算表 ID
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
# 您可以在此處直接貼上您的 Google Sheet 網址，或同樣設為環境變數
SHEET_URL = os.environ.get("SHEET_URL") 

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
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get("https://www.multpl.com/shiller-pe", headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        cape_text = soup.find('div', id='bignum').text.strip().replace('\n', '')
        return float(cape_text)
    except Exception as e:
        print(f"Error fetching CAPE: {e}")
        return 36.6

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

def should_record_history(curr_data, prev_data):
    if not prev_data: return True
    if curr_data['status'] != prev_data.get('status', ''): return True

    thresholds = {
        'vixVal': 3.0, 'vxnVal': 3.0, 'hyVal': 0.2, 't10y2yVal': 0.15,
        'ismVal': 1.0, 't10yVal': 0.2, 'brentVal': 5.0, 'cpiVal': 0.2
    }

    for key, threshold in thresholds.items():
        curr_val = curr_data.get(key, 0)
        prev_val = prev_data.get(key, 0)
        if abs(curr_val - prev_val) >= threshold:
            return True
    return False

def generate_ai_analysis(data_dict, prev_data=None):
    if not GEMINI_API_KEY: return "⚠️ 未設定 Gemini API 金鑰"
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
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
        1. 若VIX>30或極端恐慌，採取「左肩交易」策略，建議「分批資金控管」與「跌幅加碼級距」。
        2. 若VIX<15過度樂觀，說明「降槓桿」理由。
        3. 針對防禦部位，說明配置「BOXX ETF」理由。
        嚴禁使用 Markdown 符號。文字深黑。使用繁體中文。
        """
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.replace('**', '').replace('##', '').replace('*', '')
    except Exception as e:
        return f"AI 分析生成失敗：{str(e)}"

# ==========================================
# 【核心新增】同步數據至 Google Sheet
# ==========================================
def update_google_sheet(data_dict):
    if not GOOGLE_SHEETS_CREDENTIALS or not SHEET_URL:
        print("⚠️ 缺少 Google Sheet 憑證或網址，略過同步步驟。")
        return

    try:
        creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(SHEET_URL).sheet1

        # 建立 數據鍵 與 Sheet 標籤 的對應關係
        mapping = {
            "MACRO:AAA10Y": data_dict['igVal'],
            "MACRO:YIELD_SPREAD": data_dict['t10y2yVal'],
            "MACRO:AAA_SPREAD": data_dict['aaaOasVal'],
            "MACRO:HY_OAS": data_dict['hyVal'],
            "MACRO:VIX": data_dict['vixVal'],
            "MACRO:VXN": data_dict['vxnVal'],
            "MACRO:CAPE": data_dict['capeVal'],
            "MACRO:ISM": data_dict['ismVal'],
            "MACRO:CPI": data_dict['cpiVal'],
            "MACRO:US10Y": data_dict['t10yVal'],
            "MACRO:BRENT": data_dict['brentVal']
        }

        print("📊 正在同步總經指標至 Google Sheet...")
        for label, value in mapping.items():
            try:
                cell = sheet.find(label)
                # 更新在標籤右方一格
                sheet.update_cell(cell.row, cell.col + 1, value)
            except gspread.exceptions.CellNotFound:
                print(f"⚠️ 找不到標籤: {label}")
        print("✅ Google Sheet 同步完成！")
    except Exception as e:
        print(f"❌ 同步 Google Sheet 失敗: {e}")

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
            except: history = []
                
    prev_data = history[0] if len(history) > 0 else None

    # 執行 AI 分析
    print("Generating AI Analysis...")
    ai_content = generate_ai_analysis(new_data, prev_data)
    new_data["aiContent"] = ai_content
    new_data["timestamp"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    # 1. 儲存至本地 JSON
    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
        
    if should_record_history(new_data, prev_data):
        history.insert(0, new_data)
        history = history[:100]
        with open('data/history.json', 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    # 2. 【關鍵呼叫】執行 Google Sheet 同步
    update_google_sheet(new_data)

    # 3. 輸出 GitHub Actions 環境變數
    if "GITHUB_ENV" in os.environ:
        status_changed = (new_data['status'] != (prev_data.get('status', '未知') if prev_data else '未知'))
        with open(os.environ["GITHUB_ENV"], "a", encoding='utf-8') as f:
            f.write(f"STATUS_CHANGED={'true' if status_changed else 'false'}\n")
            f.write(f"NEW_STATUS={new_data['status']}\n")
            
    print("Update complete!")

if __name__ == "__main__":
    main()
