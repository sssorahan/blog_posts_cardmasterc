#!/usr/bin/env python3
"""
Blogger Auto Uploader
blog-posts 폴더의 HTML 파일을 Blogger API로 자동 예약 발행합니다.

사용법:
  python blogger_uploader.py
  python blogger_uploader.py [블로그ID]
  python blogger_uploader.py [블로그ID] [저장경로]

최초 실행 시 브라우저 OAuth 인증이 열립니다.
이후 실행부터는 자동 인증됩니다 (blogger_token.json 재사용).
"""

import os
import re
import sys
import glob
import json
import time
import webbrowser
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote

# Windows cp949 터미널에서 이모지 출력 오류 방지
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("[ERR] 필수 패키지가 없습니다. 아래 명령어로 설치하세요:")
    print("   pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES = ['https://www.googleapis.com/auth/blogger']
BASE_DIR = Path(__file__).parent
SECRETS_FILE = BASE_DIR / 'client_secrets.json'
TOKEN_FILE = BASE_DIR / 'blogger_token.json'
BLOG_ID_FILE = BASE_DIR / 'blog_id.txt'
UPLOADED_LOG = BASE_DIR / 'uploaded_posts.json'


def get_credentials():
    """OAuth 인증 처리 (최초: 브라우저, 이후: 자동 갱신)"""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not SECRETS_FILE.exists():
                print(f"[ERR] {SECRETS_FILE} 파일이 없습니다.")
                print("   블로거-API-설정가이드.txt 를 참고하세요.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS_FILE), SCOPES)
            flow.redirect_uri = "http://localhost"
            auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline", login_hint="sssorahan@gmail.com")
            print("\n" + "=" * 60)
            print("  Google 인증이 필요합니다.")
            print("=" * 60)
            print(f"\n아래 URL을 브라우저에서 여세요:\n\n  {auth_url}\n")
            webbrowser.open(auth_url)
            print("권한 허용 후 브라우저 주소창의 전체 URL을 복사해서 붙여넣으세요.")
            print("(주소창에 'localhost/?code=4/...' 형태로 보일 거예요)\n")
            redirected = input("URL 붙여넣기: ").strip()
            parsed = urlparse(redirected)
            code = parse_qs(parsed.query).get("code", [None])[0]
            if code:
                code = unquote(code)
            else:
                code = redirected.strip()
            flow.fetch_token(code=code)
            creds = flow.credentials

        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())

    return creds


def load_uploaded_log():
    """이미 업로드된 파일 목록 로드 (재실행 시 중복 방지)"""
    if UPLOADED_LOG.exists():
        with open(UPLOADED_LOG, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_uploaded_log(log):
    with open(UPLOADED_LOG, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def extract_title(html):
    """HTML에서 포스트 제목 추출"""
    # <title> 태그에서 추출 후 " | 블로그이름" 제거
    m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r'\s*\|.*$', '', m.group(1)).strip()
        if title:
            return title

    # <h1> 태그에서 추출
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()

    return "제목 없음"


def extract_body(html):
    """HTML에서 <body> 내용 추출"""
    m = re.search(r'<body[^>]*>(.*?)</body>', html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return html


def parse_schedule(base_dir):
    """포스팅스케줄-*.txt 에서 제목 → 발행시간 매핑 생성"""
    schedule = {}
    files = sorted(glob.glob(str(Path(base_dir) / '포스팅스케줄-*.txt')), reverse=True)
    if not files:
        return schedule

    with open(files[0], 'r', encoding='utf-8') as f:
        content = f.read()

    # "제목: XXX" 와 "YYYY-MM-DD (요일) HH:MM 발행" 쌍 파싱
    entries = re.split(r'\n---\n', content)
    for entry in entries:
        date_m = re.search(r'(\d{4}-\d{2}-\d{2})\s*\([^)]*\)\s*(\d{2}:\d{2})', entry)
        title_m = re.search(r'제목:\s*(.+)', entry)
        if date_m and title_m:
            publish_iso = f"{date_m.group(1)}T{date_m.group(2)}:00+09:00"
            schedule[title_m.group(1).strip()] = publish_iso

    return schedule


def match_schedule(html_title, schedule):
    """포스트 제목과 스케줄 제목을 부분 매칭으로 연결"""
    for sched_title, publish_time in schedule.items():
        if sched_title in html_title or html_title in sched_title:
            return publish_time
        # 핵심 단어 3개 이상 일치 여부 확인
        words = set(re.findall(r'[가-힣a-zA-Z0-9]{2,}', html_title))
        sched_words = set(re.findall(r'[가-힣a-zA-Z0-9]{2,}', sched_title))
        if len(words & sched_words) >= 3:
            return publish_time
    return None


def upload_posts(blog_id, base_dir):
    base_dir = Path(base_dir)
    print("\n[AUTH] Google 인증 중...", flush=True)
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)

    # 업로드 이력 로드
    uploaded = load_uploaded_log()

    # 스케줄 파싱
    schedule = parse_schedule(base_dir)
    if schedule:
        print(f"[CAL] 스케줄 {len(schedule)}개 항목 로드됨")
    else:
        print("[WARN]  스케줄 파일 없음 — 모든 포스트를 임시보관함으로 업로드합니다")

    # HTML 파일 목록
    html_files = sorted(glob.glob(str(base_dir / '*.html')))
    if not html_files:
        print("[ERR] 업로드할 HTML 파일이 없습니다. /adsense-batch 를 먼저 실행하세요.")
        return

    new_files = [f for f in html_files if Path(f).name not in uploaded]
    print(f"\n[INFO] 업로드 대상: {len(new_files)}개 (전체 {len(html_files)}개 중 신규)\n")

    if not new_files:
        print("[OK] 모든 파일이 이미 업로드되었습니다.")
        return

    success, fail = 0, 0

    for html_file in new_files:
        filename = Path(html_file).name
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()

        title = extract_title(html_content)
        body = extract_body(html_content)
        publish_time = match_schedule(title, schedule)

        try:
            post_body = {
                'title': title,
                'content': body,
            }

            # 항상 draft로 먼저 생성
            if publish_time:
                post_body['published'] = publish_time

            result = service.posts().insert(
                blogId=blog_id,
                body=post_body,
                isDraft=True
            ).execute()
            post_id = result['id']

            if publish_time:
                # publish() 호출: 미래 날짜 → SCHEDULED, 과거 날짜 → LIVE
                pub_result = service.posts().publish(
                    blogId=blog_id,
                    postId=post_id
                ).execute()
                final_status = pub_result.get('status', '?')
                if final_status == 'SCHEDULED':
                    status_label = f"예약 ({publish_time[:16].replace('T', ' ')})"
                else:
                    status_label = f"발행됨"
                post_url = pub_result.get('url', result.get('url', ''))
            else:
                status_label = "임시보관"
                post_url = result.get('url', '')

            uploaded[filename] = {
                'post_id': post_id,
                'title': title,
                'publish_time': publish_time,
                'url': post_url,
                'uploaded_at': datetime.now().isoformat()
            }
            save_uploaded_log(uploaded)

            print(f"OK [{status_label}]: {title}")
            if post_url:
                print(f"   URL: {post_url}")
            success += 1
            time.sleep(10)

        except HttpError as e:
            print(f"[ERR] 실패: {title}")
            print(f"   오류: {e}")
            fail += 1
        except Exception as e:
            print(f"[ERR] 실패: {title}")
            print(f"   오류: {e}")
            fail += 1

    print(f"\n{'='*50}")
    print(f"완료: 성공 {success}개 / 실패 {fail}개")
    if fail > 0:
        print("실패한 항목은 다시 실행하면 재시도합니다.")
    print(f"{'='*50}\n")


def update_post_schedules(blog_id, base_dir):
    """이미 업로드된 임시보관 포스트에 예약 발행 시간 설정"""
    base_dir = Path(base_dir)
    print("\n[AUTH] Google 인증 중...", flush=True)
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)

    uploaded = load_uploaded_log()
    schedule = parse_schedule(base_dir)

    if not schedule:
        print("[ERR] 포스팅스케줄-*.txt 파일이 없습니다.")
        return

    print(f"[CAL] 스케줄 {len(schedule)}개 항목 로드됨\n")

    updated, skipped, fail = 0, 0, 0
    first_published = False

    # 파일명 순서대로 처리 (001 → 010 → 017 순)
    for filename in sorted(uploaded.keys()):
        info = uploaded[filename]
        title = info['title']

        if info.get('publish_time'):
            print(f"[SKIP] 이미 처리됨: {title}")
            skipped += 1
            continue

        publish_time = match_schedule(title, schedule)
        if not publish_time:
            print(f"[WARN]  스케줄 없음: {title}")
            skipped += 1
            continue

        try:
            if not first_published:
                # 첫 번째 포스트는 즉시 발행
                service.posts().publish(
                    blogId=blog_id,
                    postId=info['post_id']
                ).execute()
                info['publish_time'] = 'NOW'
                save_uploaded_log(uploaded)
                print(f"[PUB] 즉시 발행: {title}")
                first_published = True
            else:
                # 나머지는 예약 발행
                service.posts().update(
                    blogId=blog_id,
                    postId=info['post_id'],
                    body={
                        'id': info['post_id'],
                        'title': title,
                        'published': publish_time,
                    }
                ).execute()
                info['publish_time'] = publish_time
                save_uploaded_log(uploaded)
                label = publish_time[:16].replace('T', ' ')
                print(f"[OK] 예약 설정: {title}")
                print(f"   발행 시간: {label}")

            updated += 1
            time.sleep(3)

        except HttpError as e:
            print(f"[ERR] 실패: {title}")
            print(f"   오류: {e}")
            fail += 1

    print(f"\n{'='*50}")
    print(f"완료: 예약 설정 {updated}개 / 건너뜀 {skipped}개 / 실패 {fail}개")
    print(f"{'='*50}\n")


if __name__ == '__main__':
    # --update-schedule 플래그 확인
    update_schedule_mode = '--update-schedule' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--update-schedule']

    # 블로그 ID 결정 (우선순위: 인수 > blog_id.txt)
    blog_id = None
    base_dir = str(BASE_DIR)

    if BLOG_ID_FILE.exists():
        blog_id = BLOG_ID_FILE.read_text(encoding='utf-8').strip()

    if len(args) > 0:
        blog_id = args[0]
    if len(args) > 1:
        base_dir = args[1]

    if not blog_id:
        print("[ERR] 블로그 ID가 없습니다.")
        print("   방법 1: blog_id.txt 파일에 블로그 ID 저장")
        print("   방법 2: python blogger_uploader.py [블로그ID]")
        print("\n   블로그 ID 확인 방법:")
        print("   Blogger 대시보드 URL → blogger.com/blog/posts/[여기가_블로그ID]")
        sys.exit(1)

    if update_schedule_mode:
        update_post_schedules(blog_id, base_dir)
    else:
        upload_posts(blog_id, base_dir)

