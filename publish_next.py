#!/usr/bin/env python3
"""
매일 pending_drafts.json에서 다음 초안 1개를 API로 발행합니다.
브라우저 불필요 — Windows 작업 스케줄러에서 자동 실행됩니다.
"""
import sys, json
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


def main():
    if not PENDING_FILE.exists():
        log("[중단] pending_drafts.json 없음 — create_all_drafts.py를 먼저 실행하세요.")
        sys.exit(1)

    pending = json.loads(PENDING_FILE.read_text(encoding='utf-8'))
    if not pending:
        log("[완료] 모든 초안 발행 완료. 더 이상 발행할 글이 없습니다.")
        sys.exit(0)

    uploaded = json.loads(UPLOADED_LOG.read_text(encoding='utf-8'))
    blog_id  = BLOG_ID_FILE.read_text(encoding='utf-8').strip()

    # 인증
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE),
                                                   ['https://www.googleapis.com/auth/blogger'])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding='utf-8')

    service = build('blogger', 'v3', credentials=creds)

    # 첫 번째 pending 항목 선택 (파일명 기준 정렬)
    filename = sorted(pending.keys())[0]
    info     = pending[filename]
    post_id  = info['post_id']
    title    = info['title']

    log(f"발행 시도: {title} (post_id: {post_id})")

    try:
        result = service.posts().publish(blogId=blog_id, postId=post_id).execute()
        status  = result.get('status', '?')
        post_url = result.get('url', '')

        log(f"  상태: {status}")
        log(f"  URL: {post_url}")

        # uploaded_posts.json 업데이트
        uploaded[filename] = {
            'post_id': post_id,
            'title': title,
            'publish_time': datetime.now().isoformat(),
            'url': post_url,
            'uploaded_at': datetime.now().isoformat()
        }
        UPLOADED_LOG.write_text(
            json.dumps(uploaded, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

        # pending에서 제거
        del pending[filename]
        PENDING_FILE.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

        remaining = len(pending)
        log(f"  발행 완료! 남은 글: {remaining}개")

    except HttpError as e:
        log(f"  [API 오류] {e.status_code}: {e.reason}")
        sys.exit(1)
    except Exception as e:
        log(f"  [오류] {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
