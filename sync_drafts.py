#!/usr/bin/env python3
"""
Blogger 초안 목록을 조회해 pending_drafts.json과 uploaded_posts.json을 동기화합니다.
"""
import json
import sys
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("[ERR] pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

BASE_DIR     = Path(__file__).parent
TOKEN_FILE   = BASE_DIR / 'blogger_token.json'
BLOG_ID_FILE = BASE_DIR / 'blog_id.txt'
UPLOADED_LOG = BASE_DIR / 'uploaded_posts.json'
PENDING_FILE = BASE_DIR / 'pending_drafts.json'

def main():
    blog_id = BLOG_ID_FILE.read_text(encoding='utf-8').strip()

    creds = Credentials.from_authorized_user_file(
        str(TOKEN_FILE), ['https://www.googleapis.com/auth/blogger'])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding='utf-8')

    service = build('blogger', 'v3', credentials=creds)

    # 현재 repo 상태 로드
    uploaded = json.loads(UPLOADED_LOG.read_text(encoding='utf-8'))
    pending  = json.loads(PENDING_FILE.read_text(encoding='utf-8')) if PENDING_FILE.exists() else {}

    # 이미 추적 중인 post_id 목록
    tracked_ids = {v['post_id'] for v in {**uploaded, **pending}.values()}

    # Blogger에서 모든 초안 조회
    print("[INFO] Blogger 초안 목록 조회 중...")
    draft_posts = []
    page_token = None
    while True:
        resp = service.posts().list(
            blogId=blog_id,
            status='draft',
            maxResults=50,
            pageToken=page_token,
            fields='items(id,title,published),nextPageToken'
        ).execute()
        draft_posts.extend(resp.get('items', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    print(f"[INFO] Blogger 초안 {len(draft_posts)}개 확인됨")

    # 로컬 HTML 파일 제목 맵 생성
    import re
    html_title_map = {}
    for html_file in sorted(BASE_DIR.glob('*.html')):
        content = html_file.read_text(encoding='utf-8', errors='replace')
        m = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            html_title_map[title] = html_file.name

    added_pending = 0
    added_uploaded = 0

    for post in draft_posts:
        post_id = post['id']
        title   = post['title']

        # 이미 추적 중이면 스킵
        if post_id in tracked_ids:
            continue

        # 로컬 HTML 파일과 매칭
        filename = html_title_map.get(title)
        if not filename:
            print(f"  [WARN] 매칭 HTML 없음: {title}")
            continue

        now_iso = datetime.now().isoformat()

        # uploaded_posts.json에 없으면 추가 (draft 상태)
        if filename not in uploaded:
            uploaded[filename] = {
                'post_id': post_id,
                'title': title,
                'publish_time': None,
                'url': '',
                'uploaded_at': now_iso
            }
            added_uploaded += 1

        # pending_drafts.json에 없으면 추가
        if filename not in pending:
            pending[filename] = {
                'post_id': post_id,
                'title': title,
                'created_at': now_iso
            }
            added_pending += 1
            print(f"  [OK] pending 추가: {title}")

        tracked_ids.add(post_id)

    UPLOADED_LOG.write_text(json.dumps(uploaded, ensure_ascii=False, indent=2), encoding='utf-8')
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n[완료] uploaded_posts.json +{added_uploaded}개 / pending_drafts.json +{added_pending}개")
    print(f"       현재 발행 대기: {len(pending)}개")

if __name__ == '__main__':
    main()
