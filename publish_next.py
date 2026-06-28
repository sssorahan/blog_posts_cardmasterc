#!/usr/bin/env python3
"""
매일 pending_drafts.json에서 다음 초안 1개를 발행합니다.
pending_drafts.json이 비어있으면 HTML 파일을 직접 읽어 업로드 후 발행합니다.
"""
import sys, json, re
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("[ERR] pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

BASE_DIR      = Path(__file__).parent
TOKEN_FILE    = BASE_DIR / 'blogger_token.json'
BLOG_ID_FILE  = BASE_DIR / 'blog_id.txt'
UPLOADED_LOG  = BASE_DIR / 'uploaded_posts.json'
PENDING_FILE  = BASE_DIR / 'pending_drafts.json'
LOG_FILE      = BASE_DIR / 'publish_log.txt'


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def extract_title(html):
    m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    return "제목 없음"


def extract_body(html):
    m = re.search(r'<body[^>]*>(.*?)</body>', html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return html


def get_service():
    creds = Credentials.from_authorized_user_file(
        str(TOKEN_FILE), ['https://www.googleapis.com/auth/blogger'])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding='utf-8')
    return build('blogger', 'v3', credentials=creds)


def publish_from_pending(service, blog_id, pending, uploaded):
    """pending_drafts.json의 첫 번째 초안을 발행"""
    filename = sorted(pending.keys())[0]
    info     = pending[filename]
    post_id  = info['post_id']
    title    = info['title']

    log(f"발행 시도: {title} (post_id: {post_id})")

    result   = service.posts().publish(blogId=blog_id, postId=post_id).execute()
    status   = result.get('status', '?')
    post_url = result.get('url', '')

    log(f"  상태: {status}")
    log(f"  URL: {post_url}")

    uploaded[filename] = {
        'post_id': post_id,
        'title': title,
        'publish_time': datetime.now().isoformat(),
        'url': post_url,
        'uploaded_at': datetime.now().isoformat()
    }
    UPLOADED_LOG.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2), encoding='utf-8')

    del pending[filename]
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding='utf-8')

    log(f"  발행 완료! 남은 글: {len(pending)}개")


def upload_and_publish_html(service, blog_id, pending, uploaded):
    """HTML 파일을 직접 읽어 Blogger에 업로드 후 즉시 발행"""
    # 아직 업로드되지 않은 HTML 파일 찾기
    html_files = sorted(BASE_DIR.glob('post_*.html'))
    new_files  = [f for f in html_files if f.name not in uploaded]

    log(f"[디버그] HTML 파일: {len(html_files)}개 / 미발행: {len(new_files)}개 / uploaded 키: {len(uploaded)}개")

    if not new_files:
        log("[완료] 모든 포스트 발행 완료. 더 이상 발행할 글이 없습니다.")
        sys.exit(0)

    target = new_files[0]
    html   = target.read_text(encoding='utf-8', errors='replace')
    title  = extract_title(html)
    body   = extract_body(html)

    log(f"신규 업로드+발행: {title} ({target.name})")

    # 직접 발행 (draft → publish 2단계 대신 insert 1단계)
    result   = service.posts().insert(
        blogId=blog_id,
        body={'title': title, 'content': body}
    ).execute()
    post_id  = result['id']
    status   = result.get('status', '?')
    post_url = result.get('url', '')

    log(f"  상태: {status}")
    log(f"  URL: {post_url}")

    uploaded[target.name] = {
        'post_id': post_id,
        'title': title,
        'publish_time': datetime.now().isoformat(),
        'url': post_url,
        'uploaded_at': datetime.now().isoformat()
    }
    UPLOADED_LOG.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2), encoding='utf-8')

    remaining = len([f for f in html_files if f.name not in uploaded])
    log(f"  발행 완료! 남은 글: {remaining}개")


def main():
    blog_id  = BLOG_ID_FILE.read_text(encoding='utf-8').strip()
    uploaded = json.loads(UPLOADED_LOG.read_text(encoding='utf-8'))
    pending  = json.loads(PENDING_FILE.read_text(encoding='utf-8')) if PENDING_FILE.exists() else {}

    service = get_service()

    try:
        if pending:
            publish_from_pending(service, blog_id, pending, uploaded)
        else:
            upload_and_publish_html(service, blog_id, pending, uploaded)

    except HttpError as e:
        log(f"  [API 오류] {e.status_code}: {e.reason}")
        sys.exit(1)
    except Exception as e:
        log(f"  [오류] {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
