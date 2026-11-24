import os
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 1. 공항 목록 읽기
with open("airports.txt", "r", encoding="utf-8") as f:
    AIRPORTS = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]

os.makedirs("images", exist_ok=True)

# 2. 최근 METAR 전체 가져오기 (최근 4시간, 줄임 없이 전체)
def fetch_metars(icao):
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&hours=4"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8").strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return lines if lines else [f"{icao} METAR 데이터를 불러오지 못했습니다."]
    except Exception as e:
        return [f"{icao} METAR 조회 오류: {e}"]

# 3. 최신 METAR 요약 파싱
def parse_latest_metar(metar_line):
    wind, vis, temp, qnh, cat = "-", "-", "-", "-", "VFR"

    m_wind = re.search(r"\b(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT\b", metar_line)
    if m_wind:
        w_dir, w_spd, _, w_gst = m_wind.groups()
        wind = f"{w_dir}°/{w_spd}kt" + (f" G{w_gst}" if w_gst else "")

    if "CAVOK" in metar_line:
        vis = "CAVOK (10km+)"
    else:
        m_vis = re.search(r"\b(\d{4})\b", metar_line)
        if m_vis:
            v_val = int(m_vis.group(1))
            vis = "10km+" if v_val == 9999 else f"{v_val}m"
            if v_val < 1600:
                cat = "LIFR"
            elif v_val < 5000:
                cat = "IFR"
            elif v_val < 8000:
                cat = "MVFR"

    m_temp = re.search(r"\b(M?\d{2})/(M?\d{2})\b", metar_line)
    if m_temp:
        t_str = m_temp.group(1).replace("M", "-")
        d_str = m_temp.group(2).replace("M", "-")
        temp = f"{int(t_str)}°C / {int(d_str)}°C"

    m_qnh = re.search(r"\b(Q\d{4}|A\d{4})\b", metar_line)
    if m_qnh:
        qnh = m_qnh.group(1)

    return {"wind": wind, "vis": vis, "temp": temp, "qnh": qnh, "cat": cat}

# 4. Headless Chrome으로 Windy 7일 예보 표만 DOM 적출 캡처
def capture_windy(airports):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=3200,1200")
    options.add_argument("--force-device-scale-factor=1")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 25)
    captured = {}

    try:
        for icao in airports:
            print(f"[{icao}] Windy 예보 표 적출 시작...", flush=True)
            img_path = f"images/{icao}.png"
            try:
                driver.get(f"https://www.windy.com/airport/{icao}")
                time.sleep(6)

                # 예보 표(Meteogram / Detail table) 대기
                table_el = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#detail-data-table, table.forecast-table, .table-wrapper table"))
                )
                time.sleep(2)

                # [핵심] 지도/껍데기 전부 숨기고 예보 표 알맹이만 깨끗한 박스로 적출
                box = driver.execute_script("""
                    const table = arguments[0];
                    const existing = document.getElementById('clean-capture-box');
                    if (existing) existing.remove();

                    const box = document.createElement('div');
                    box.id = 'clean-capture-box';
                    box.style.position = 'fixed';
                    box.style.top = '0';
                    box.style.left = '0';
                    box.style.zIndex = '9999999';
                    box.style.background = '#ffffff';
                    box.style.padding = '12px';
                    box.style.display = 'inline-block';

                    // 표를 통째로 새 박스로 이동 (스타일 및 아이콘 유지)
                    box.appendChild(table);
                    document.body.appendChild(box);

                    // 나머지 지도, 팝업, 메뉴 전부 숨김
                    Array.from(document.body.children).forEach(el => {
                        if (el.id !== 'clean-capture-box') {
                            el.style.display = 'none';
                        }
                    });
                    document.body.style.background = '#ffffff';
                    document.body.style.overflow = 'visible';

                    return box;
                """, table_el)

                time.sleep(1)

                # 표 실제 너비에 맞춰 창 크기 자동 조정 (가로 잘림 방지)
                width = driver.execute_script("return arguments[0].scrollWidth;", box)
                height = driver.execute_script("return arguments[0].scrollHeight;", box)
                driver.set_window_size(max(width + 40, 1400), max(height + 40, 600))
                time.sleep(0.5)

                box.screenshot(img_path)
                captured[icao] = img_path
                print(f" -> [{icao}] 적출 캡처 완료 ({width}x{height})", flush=True)
            except Exception as e:
                print(f" -> [{icao}] 캡처 실패: {e}", flush=True)
                captured[icao] = ""
    finally:
        driver.quit()

    return captured

# 5. 데이터 수집 실행
kst = timezone(timedelta(hours=9))
now_kst = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")
now_utc = datetime.now(timezone.utc).strftime("%d%H%MZ")

captured_imgs = capture_windy(AIRPORTS)
airport_data = []

for icao in AIRPORTS:
    metars = fetch_metars(icao)
    summary = parse_latest_metar(metars[0])
    airport_data.append({
        "icao": icao,
        "metars": metars,
        "summary": summary,
        "img": captured_imgs.get(icao, "")
    })

# 6. HTML 대시보드 생성
tiles_html = ""
cards_html = ""

for item in airport_data:
    icao = item["icao"]
    s = item["summary"]
    cat_cls = s["cat"].lower()
    tiles_html += f"""
    <button class="tile" onclick="filterAirport('{icao}')" data-icao="{icao}">
      <div class="tile-top">
        <span class="icao">{icao}</span>
        <span class="badge {cat_cls}">{s['cat']}</span>
      </div>
      <div class="tile-meta">
        <div><span>WIND</span><strong>{s['wind']}</strong></div>
        <div><span>VIS</span><strong>{s['vis']}</strong></div>
        <div><span>TEMP</span><strong>{s['temp']}</strong></div>
        <div><span>QNH</span><strong>{s['qnh']}</strong></div>
      </div>
    </button>
    """

    metar_lines_html = "\n".join([f'<div class="metar-line">{line}</div>' for line in item["metars"]])
    img_html = (
        f'<img src="{item["img"]}?t={int(time.time())}" alt="{icao} 7-day forecast" onclick="openModal(this.src)" loading="lazy">'
        if item["img"]
        else '<div class="no-img">예보 표를 불러오지 못했습니다.</div>'
    )

    cards_html += f"""
    <section class="card" data-icao="{icao}">
      <div class="card-header">
        <div class="card-title">
          <h2>{icao}</h2>
          <span class="badge {cat_cls}">{s['cat']}</span>
        </div>
        <div class="card-stats">
          <span>WIND <b>{s['wind']}</b></span>
          <span>VIS <b>{s['vis']}</b></span>
          <span>TEMP <b>{s['temp']}</b></span>
          <span>QNH <b>{s['qnh']}</b></span>
        </div>
      </div>
      <div class="metar-box">
        <div class="section-label">METAR ({len(item['metars'])}건 전체 표시)</div>
        <div class="metar-list">{metar_lines_html}</div>
      </div>
      <div class="forecast-box">
        <div class="section-label">WINDY 7-DAY FORECAST <small>(클릭 시 확대 / 모바일 좌우 스크롤)</small></div>
        <div class="img-scroll">{img_html}</div>
      </div>
    </section>
    """

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aviation Weather Briefing</title>
<style>
  :root {{
    --bg: #f4f6f9; --surface: #ffffff; --text: #111827; --muted: #6b7280;
    --border: #e5e7eb; --accent: #2563eb; --code-bg: #f8fafc;
  }}
  [data-theme="dark"] {{
    --bg: #0b1120; --surface: #111827; --text: #f3f4f6; --muted: #9ca3af;
    --border: #1f2937; --accent: #60a5fa; --code-bg: #0f172a;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); }}
  header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 20px; position: sticky; top: 0; z-index: 10; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }}
  .brand h1 {{ margin: 0; font-size: 1.2rem; letter-spacing: -0.02em; }}
  .brand .time {{ font-size: 0.85rem; color: var(--muted); margin-top: 2px; }}
  .controls {{ display: flex; gap: 8px; }}
  .btn {{ background: var(--bg); color: var(--text); border: 1px solid var(--border); padding: 7px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; font-weight: 600; }}
  .btn:hover {{ border-color: var(--accent); }}
  main {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
  .tiles {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .tile {{ text-align: left; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; cursor: pointer; color: inherit; transition: border-color .15s; }}
  .tile:hover, .tile.active {{ border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }}
  .tile-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .icao {{ font-weight: 800; font-size: 1.05rem; font-family: monospace; }}
  .tile-meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.78rem; }}
  .tile-meta span {{ display: block; color: var(--muted); font-size: 0.68rem; }}
  .badge {{ font-size: 0.7rem; font-weight: 700; padding: 2px 7px; border-radius: 999px; color: #fff; }}
  .badge.vfr {{ background: #16a34a; }} .badge.mvfr {{ background: #2563eb; }}
  .badge.ifr {{ background: #dc2626; }} .badge.lifr {{ background: #9333ea; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; margin-bottom: 20px; }}
  .card-header {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid var(--border); margin-bottom: 14px; }}
  .card-title {{ display: flex; align-items: center; gap: 10px; }}
  .card-title h2 {{ margin: 0; font-family: monospace; font-size: 1.35rem; }}
  .card-stats {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.85rem; color: var(--muted); }}
  .card-stats b {{ color: var(--text); margin-left: 4px; }}
  .section-label {{ font-size: 0.75rem; font-weight: 700; color: var(--muted); margin-bottom: 8px; letter-spacing: 0.03em; }}
  .metar-list {{ background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.84rem; line-height: 1.6; overflow-x: auto; }}
  .metar-line {{ padding: 4px 0; border-bottom: 1px dashed var(--border); white-space: pre-wrap; word-break: break-word; }}
  .metar-line:last-child {{ border-bottom: none; }}
  .forecast-box {{ margin-top: 16px; }}
  .img-scroll {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; background: #fff; }}
  .img-scroll img {{ display: block; max-width: none; height: auto; cursor: zoom-in; }}
  .no-img {{ padding: 24px; text-align: center; color: var(--muted); }}
  .modal {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 100; align-items: center; justify-content: center; padding: 20px; }}
  .modal.open {{ display: flex; }}
  .modal img {{ max-width: 96vw; max-height: 92vh; border-radius: 8px; background: #fff; }}
</style>
</head>
<body>
<header>
  <div class="brand">
    <h1>✈️ Aviation Weather Briefing</h1>
    <div class="time">최종 업데이트: {now_kst} ({now_utc})</div>
  </div>
  <div class="controls">
    <button class="btn" onclick="filterAirport('ALL')">전체 공항 보기</button>
    <button class="btn" onclick="toggleTheme()">🌙 야간/주간 모드</button>
  </div>
</header>
<main>
  <div class="tiles">{tiles_html}</div>
  <div id="cards">{cards_html}</div>
</main>
<div id="modal" class="modal" onclick="this.classList.remove('open')">
  <img id="modal-img" src="" alt="확대 보기">
</div>
<script>
  let activeIcao = 'ALL';
  function filterAirport(icao) {{
    activeIcao = (activeIcao === icao && icao !== 'ALL') ? 'ALL' : icao;
    document.querySelectorAll('.card').forEach(c => {{
      c.style.display = (activeIcao === 'ALL' || c.dataset.icao === activeIcao) ? 'block' : 'none';
    }});
    document.querySelectorAll('.tile').forEach(t => {{
      t.classList.toggle('active', t.dataset.icao === activeIcao);
    }});
  }}
  function toggleTheme() {{
    const cur = document.documentElement.getAttribute('data-theme');
    document.documentElement.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
  }}
  function openModal(src) {{
    document.getElementById('modal-img').src = src;
    document.getElementById('modal').classList.add('open');
  }}
</script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("index.html 생성 완료!", flush=True)
