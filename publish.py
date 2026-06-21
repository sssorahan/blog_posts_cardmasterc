#!/usr/bin/env python3
"""
Blogger 자동 발행 (undetected-chromedriver)
사용법:
  python publish.py                          # 미발행 첫 번째 글 자동 선택
  python publish.py post_006_DC형ETF운용전략.html
"""
import sys, io, re, json, time, glob
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("pip install undetected-chromedriver selenium")
    sys.exit(1)

BASE_DIR     = Path(__file__).parent
BLOG_ID_FILE = BASE_DIR / 'blog_id.txt'
UPLOADED_LOG = BASE_DIR / 'uploaded_posts.json'


def extract_title(html):
    m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        t = re.sub(r'\s*\|.*$', '', m.group(1)).strip()
        if t:
            return t
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    return "제목 없음"


def extract_body(html):
    m = re.search(r'<body[^>]*>(.*?)</body>', html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else html


def pick_target(uploaded):
    files = sorted(glob.glob(str(BASE_DIR / 'post_*.html')))
    for f in files:
        if Path(f).name not in uploaded:
            return Path(f)
    return None


def js_click(driver, el):
    driver.execute_script("arguments[0].click();", el)


def main():
    blog_id = BLOG_ID_FILE.read_text(encoding='utf-8').strip()

    with open(UPLOADED_LOG, 'r', encoding='utf-8') as f:
        uploaded = json.load(f)

    if len(sys.argv) > 1:
        target = BASE_DIR / sys.argv[1]
    else:
        target = pick_target(uploaded)

    if not target or not target.exists():
        print("발행할 파일이 없습니다.")
        sys.exit(0)

    if target.name in uploaded:
        print(f"이미 업로드됨: {target.name}")
        sys.exit(0)

    html_content = target.read_text(encoding='utf-8')
    title     = extract_title(html_content)
    body_html = extract_body(html_content)
    print(f"발행 대상: {title}")

    options = uc.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--start-maximized')

    print("Chrome 시작... 작업표시줄에서 새 Chrome 창 찾아 로그인하세요.")
    driver = uc.Chrome(options=options, headless=False)

    try:
        # 1. Blogger 포스트 목록으로 이동
        driver.get(f'https://www.blogger.com/blog/posts/{blog_id}')
        time.sleep(3)

        # 2. 로그인 대기 (최대 5분)
        print("로그인 대기 중... (Chrome 창에서 로그인해주세요)")
        for i in range(150):
            time.sleep(2)
            url = driver.current_url
            if 'blogger.com' in url and 'accounts.google.com' not in url:
                print(f"  로그인 완료! ({i*2}초)")
                break
            if i % 15 == 0 and i > 0:
                print(f"  {i*2}초 경과...")
        else:
            print("[실패] 로그인 대기 시간 초과")
            driver.quit()
            sys.exit(1)

        time.sleep(2)

        # 3. "새 글 작성" 버튼 클릭 (JS)
        print("새 글 작성 버튼 클릭...")
        btns = driver.find_elements(By.XPATH, '//div[@aria-label="새 글 작성"]')
        if not btns:
            print("[실패] 새 글 작성 버튼 없음")
            driver.quit()
            sys.exit(1)
        js_click(driver, btns[-1])
        time.sleep(5)  # 에디터 로딩 대기
        print(f"  에디터 URL: {driver.current_url[:70]}")

        # 4. 제목 입력
        print("제목 입력 중...")
        title_ok = False

        # 방법 A: input 태그 (첫 번째)
        try:
            inputs = driver.find_elements(By.TAG_NAME, 'input')
            # 화면에 보이는 첫 번째 input 찾기
            for inp in inputs:
                if inp.is_displayed() and inp.is_enabled():
                    inp.click()
                    time.sleep(0.3)
                    inp.send_keys(Keys.CONTROL + 'a')
                    inp.send_keys(title)
                    title_ok = True
                    print("  완료 (input[0])")
                    break
        except Exception as e:
            print(f"  input 방법 실패: {e}")

        # 방법 B: 화면 상단 클릭 후 입력
        if not title_ok:
            try:
                actions = ActionChains(driver)
                actions.move_by_offset(640, 95).click().perform()
                time.sleep(0.3)
                actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                actions.send_keys(title).perform()
                title_ok = True
                print("  완료 (좌표 클릭)")
            except Exception as e:
                print(f"  좌표 클릭 실패: {e}")

        if not title_ok:
            print("[실패] 제목 입력 불가")
            driver.save_screenshot('error_title.png')
            driver.quit()
            sys.exit(1)

        time.sleep(0.5)

        # 5. HTML 모드 확인 및 전환
        print("HTML 모드 확인...")
        # < > 버튼이 있는지 확인하고 클릭
        try:
            html_btn = driver.find_element(By.XPATH,
                '//button[contains(@aria-label,"HTML") or contains(@title,"HTML")] | '
                '//*[text()="< >" or text()="HTML"]'
            )
            js_click(driver, html_btn)
            time.sleep(1)
            print("  HTML 모드 전환 완료")
        except Exception:
            print("  HTML 모드 버튼 없음 (이미 HTML 모드일 수 있음)")

        # 6. 본문 입력 — 메인 에디터 영역 클릭 후 Ctrl+A → 붙여넣기
        print("본문 입력 중...")
        content_ok = False

        # 방법 A: 화면 중앙 에디터 영역 클릭 후 키 입력
        try:
            # 에디터 영역은 좌측 큰 흰 영역 (우측 설정 패널 제외)
            # 창 크기 기준 대략 (640, 400)
            win_w = driver.execute_script("return window.innerWidth")
            win_h = driver.execute_script("return window.innerHeight")
            editor_x = int(win_w * 0.42)   # 우측 설정 패널 제외
            editor_y = int(win_h * 0.5)
            actions = ActionChains(driver)
            actions.move_by_offset(editor_x, editor_y).click().perform()
            time.sleep(0.5)
            # Ctrl+A로 기존 내용 선택 후 삭제
            ActionChains(driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
            time.sleep(0.2)
            ActionChains(driver).send_keys(Keys.DELETE).perform()
            time.sleep(0.2)
            # 클립보드에 HTML 넣고 Ctrl+V로 붙여넣기
            driver.execute_script(f"""
                const text = arguments[0];
                navigator.clipboard.writeText(text).catch(() => {{
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                }});
            """, body_html)
            time.sleep(0.3)
            ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
            time.sleep(1)
            content_ok = True
            print("  완료 (에디터 영역 클릭 + 붙여넣기)")
        except Exception as e:
            print(f"  에디터 클릭 실패: {e}")

        # 방법 B: JS로 textarea에 직접 설정 (가장 큰 textarea)
        if not content_ok:
            try:
                textareas = driver.find_elements(By.TAG_NAME, 'textarea')
                # 가장 큰 textarea 찾기
                best_ta = max(textareas, key=lambda t: t.size.get('height', 0) * t.size.get('width', 0), default=None)
                if best_ta:
                    driver.execute_script("""
                        arguments[0].value = arguments[1];
                        arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
                        arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
                    """, best_ta, body_html)
                    content_ok = True
                    print("  완료 (largest textarea)")
            except Exception as e:
                print(f"  textarea 실패: {e}")

        if not content_ok:
            print("[실패] 본문 입력 불가")
            driver.save_screenshot('error_content.png')
            driver.quit()
            sys.exit(1)

        time.sleep(1)
        driver.save_screenshot('debug_before_publish.png')

        # 7. 게시 버튼 클릭
        print("게시 버튼 클릭 중...")
        published = False

        # 방법 A: JS로 텍스트가 "게시"인 모든 요소 탐색
        try:
            result = driver.execute_script("""
                const allEls = document.querySelectorAll('*');
                for (const el of allEls) {
                    if (el.children.length === 0 && el.textContent.trim() === '게시') {
                        return el;
                    }
                }
                // aria-label로도 찾기
                const byLabel = document.querySelector('[aria-label="게시"]');
                if (byLabel) return byLabel;
                return null;
            """)
            if result:
                driver.execute_script("arguments[0].click();", result)
                time.sleep(5)
                published = True
                print("  완료 (JS 텍스트 탐색)")
        except Exception as e:
            print(f"  JS 탐색 실패: {e}")

        # 방법 B: 우상단 좌표 클릭
        if not published:
            try:
                win_w = driver.execute_script("return window.innerWidth")
                # 게시 버튼은 우상단 — 창 너비에서 약 40px 안쪽, 높이 27px
                pub_x = win_w - 40
                pub_y = 27
                ActionChains(driver).move_by_offset(pub_x, pub_y).click().perform()
                time.sleep(5)
                published = True
                print("  완료 (우상단 좌표 클릭)")
            except Exception as e:
                print(f"  좌표 클릭 실패: {e}")
                driver.save_screenshot('error_publish.png')

        final_url = driver.current_url

        if published:
            uploaded[target.name] = {
                'post_id': 'via-browser',
                'title': title,
                'publish_time': datetime.now().isoformat(),
                'url': final_url,
                'uploaded_at': datetime.now().isoformat()
            }
            with open(UPLOADED_LOG, 'w', encoding='utf-8') as f:
                json.dump(uploaded, f, ensure_ascii=False, indent=2)
            print(f"\n발행 완료!")
            print(f"  제목: {title}")
            print(f"  URL : {final_url}")
        else:
            print("\n[실패] 발행 버튼을 찾지 못했습니다.")

        time.sleep(3)

    finally:
        driver.quit()


if __name__ == '__main__':
    main()
