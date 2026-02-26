from urllib import robotparser


def can_fetch(url, user_agent='*'):
    # 1. robots.txt 주소 생성
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"

    # 2. RobotFileParser 설정
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()  # robots.txt 파일 읽기
    except Exception as e:
        print(f"robots.txt를 읽을 수 없습니다: {e}")
        # 읽기 실패 시 보수적으로 접근하거나 기본값 설정
        return False

        # 3. 특정 URL에 대해 크롤링이 허용되는지 확인
    return rp.can_fetch(user_agent, url)


# 사용 예시
target_url = "https://example.com/notices/123"
if can_fetch(target_url, user_agent='MyBotName'):
    print("크롤링 가능!")
else:
    print("Disallow 설정됨: 크롤링 금지")