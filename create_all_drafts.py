#!/usr/bin/env python3
"""
브라우저 1회 실행으로 미발행 글 전체를 Blogger 초안으로 저장
이후 publish_next.py 가 매일 1개씩 API로 발행합니다.
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

BASE_DIR      = Path(__file__).parent
BLOG_ID_FILE  = BASE_DIR / 'blog_id.txt'
UPLOADED_LOG  = BASE_DIR / 'uploaded_posts.json'
PENDING_FILE  = BASE_DIR / 'pending_drafts.json'   # 초안 ID 저장


def extract_title(html):
    m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        t = re.sub(r'\s*\|.*$', '', m.group(1)).strip()
        if t: return t
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
    if m: return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    return "제목 없음"


def extract_body(html):
    m = re.search(r'<body[^>]*>(.*?)</body>', html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else html


def js_click(driver, el):
    driver.execute_script("arguments[0].click();", el)


def dismiss_alert(driver):
    try:
        alert = driver.switch_to.alert
        alert.accept()
        time.sleep(1)
    except Exception:
        pass


def create_one_draft(driver, blog_id, title, body_html):
    """새 글 작성 버튼 클릭 → 제목/본문 입력 → 초안 저장 → post_id 반환"""
    # 혹시 남아 있는 Alert 처리
    dismiss_alert(driver)

    # 새 글 작성 버튼 클릭
    btns = driver.find_elements(By.XPATH, '//div[@aria-label="새 글 작성"]')
    if not btns:
        raise Exception("새 글 작성 버튼 없음")
    js_click(driver, btns[-1])
    time.sleep(5)

    editor_url = driver.current_url
    m = re.search(r'/edit/\d+/(\d+)', editor_url)
    post_id = m.group(1) if m else None

    # 제목 입력
    inputs = driver.find_elements(By.TAG_NAME, 'input')
    for inp in inputs:
        if inp.is_displayed() and inp.is_enabled():
            inp.click()
            time.sleep(0.3)
            inp.send_keys(Keys.CONTROL + 'a')
            inp.send_keys(title)
            break

    time.sleep(0.5)

    # 본문 에디터 클릭 — body 요소 기준 상대 오프셋 사용 (move_by_offset 은 누적이라 범위 초과 위험)
    body_el = driver.find_element(By.TAG_NAME, 'body')
    win_w = driver.execute_script("return window.innerWidth")
    win_h = driver.execute_script("return window.innerHeight")
    # body 중심(0,0) 기준으로 에디터 위치 오프셋
    offset_x = int(win_w * 0.42) - int(win_w / 2)
    offset_y = 0
    ActionChains(driver).move_to_element_with_offset(body_el, offset_x, offset_y).click().perform()
    time.sleep(0.5)

    ActionChains(driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
    time.sleep(0.2)
    ActionChains(driver).send_keys(Keys.DELETE).perform()
    time.sleep(0.2)
    driver.execute_script("""
        const text = arguments[0];
        navigator.clipboard.writeText(text).catch(() => {
            const ta = document.createElement('textarea');
            ta.value = text; document.body.appendChild(ta);
            ta.select(); document.execCommand('copy');
            document.body.removeChild(ta);
        });
    """, body_html)
    time.sleep(0.3)
    ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
    time.sleep(1)

    # 자동 저장 대기
    time.sleep(4)

    # 포스트 목록으로 돌아가기 — Alert(미저장 경고) 발생 시 수락
    driver.get(f'https://www.blogger.com/blog/posts/{blog_id}')
    time.sleep(2)
    dismiss_alert(driver)
    time.sleep(3)

    return post_id


def main():
    blog_id = BLOG_ID_FILE.read_text(encoding='utf-8').strip()

    with open(UPLOADED_LOG, 'r', encoding='utf-8') as f:
        uploaded = json.load(f)

    # 미발행 파일 목록
    html_files = [Path(f) for f in sorted(glob.glob(str(BASE_DIR / 'post_*.html')))
                  if Path(f).name not in uploaded]

    if not html_files:
        print("미발행 파일 없음")
        sys.exit(0)

    # 기존 pending_drafts 로드
    pending = {}
    if PENDING_FILE.exists():
        pending = json.loads(PENDING_FILE.read_text(encoding='utf-8'))

    # 이미 초안 만들어진 파일 제외
    remaining = [f for f in html_files if f.name not in pending]
    if not remaining:
        print(f"이미 모든 초안 생성됨 ({len(pending)}개). publish_next.py 를 실행하세요.")
        sys.exit(0)

    print(f"초안 생성 대상: {len(remaining)}개")
    for f in remaining:
        print(f"  {f.name}")

    # Chrome 실행
    options = uc.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--start-maximized')

    print("\nChrome 시작... 작업표시줄에서 새 Chrome 창 찾아 로그인하세요.")
    driver = uc.Chrome(options=options, headless=False, version_main=149)

    try:
        driver.get(f'https://www.blogger.com/blog/posts/{blog_id}')
        time.sleep(3)

        # 로그인 대기
        print("로그인 대기 중...")
        for i in range(300):  # 최대 10분
            time.sleep(2)
            url = driver.current_url
            if 'blogger.com' in url and 'accounts.google.com' not in url:
                print(f"  로그인 완료! ({i*2}초)")
                break
            if i % 15 == 0 and i > 0:
                print(f"  {i*2}초 경과... (Chrome 창 찾아 로그인해주세요)")
        else:
            print("[실패] 로그인 시간 초과")
            driver.quit()
            sys.exit(1)

        time.sleep(2)

        # 각 파일에 대해 초안 생성
        for idx, target in enumerate(remaining):
            html = target.read_text(encoding='utf-8')
            title     = extract_title(html)
            body_html = extract_body(html)

            print(f"\n[{idx+1}/{len(remaining)}] {target.name}")
            print(f"  제목: {title}")

            try:
                post_id = create_one_draft(driver, blog_id, title, body_html)
                pending[target.name] = {
                    'post_id': post_id,
                    'title': title,
                    'created_at': datetime.now().isoformat()
                }
                PENDING_FILE.write_text(
                    json.dumps(pending, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )
                print(f"  초안 저장 완료 (post_id: {post_id})")
            except Exception as e:
                print(f"  [오류] {e}")

        print(f"\n전체 완료: {len(pending)}개 초안 저장됨")
        print("이제 publish_next.py 가 매일 자동 발행합니다.")

        time.sleep(2)
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
