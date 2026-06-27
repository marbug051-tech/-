import os
import sys
import logging
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
# =================================================================
# ⚠️ [인증키 주입] 복사하신 64글자 인증키를 여기에 입력하세요.
# =================================================================
MY_API_KEY = "a5f9566584e40431a1de3aee64bc26344288646bf8328f502724b10f8883ec6c"
# =================================================================

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)


def fetch_all_stations():
    """1. XML 포맷 전용 기계적 파싱 및 데이터 수집 함수"""
    base_url = "http://apis.data.go.kr/B552587/ParkingInfoService_v2/getParkingInfoList_v2"

    params = {
        'serviceKey': MY_API_KEY,
        'pageNo': 1,
        'numOfRows': 1000,
        '_type': 'json'
    }

    try:
        logging.info("📡 부산시설공단 API 서버로부터 실시간 XML 추출 중...")
        response = requests.get(base_url, params=params, timeout=15)
        raw_text = response.text.strip()

        # XML 대 파싱 시작
        root = ET.fromstring(raw_text)

        # 결과 코드 검증
        result_code = root.find('.//resultCode')
        result_msg = root.find('.//resultMsg')

        code_text = result_code.text if result_code is not None else 'Unknown'
        msg_text = result_msg.text if result_msg is not None else 'Unknown'

        if code_text != '00':
            logging.error(f"❌ API 서버 반환 에러: {msg_text} (코드: {code_text})")
            return pd.DataFrame()

        items_node = root.find('.//items')
        if items_node is None:
            logging.warning("⚠️ 수집할 주차장 항목(items)이 존재하지 않습니다.")
            return pd.DataFrame()

        all_items = []
        for item_node in items_node.findall('item'):
            # 실시간 추출 필드 매핑 딕셔너리 빌드
            item_data = {
                '주차장명': item_node.findtext('parknm', '이름 없음'),
                '최대주차가능대수': item_node.findtext('maxcnt', '0'),
                '현재주차대수': item_node.findtext('parkingcnt', '0'),
                '최종갱신일시': item_node.findtext('lastupdatetime', datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')),
                # 본 API에서 제공하지 않는 필수 필드는 시스템 다운 방지를 위해 기본값 부여
                '위도': 35.1796,  # 위경도가 없으므로 부산시청 중심 좌표 기본 배치
                '경도': 129.0756,
                '주소': '부산시 기타구'
            }
            all_items.append(item_data)

        total_count_node = root.find('.//totalCount')
        total_count = total_count_node.text if total_count_node is not None else len(all_items)
        logging.info(f"🎯 서버 동기화 대상 총 주차장 수: {total_count}개 (성공적으로 {len(all_items)}개 파싱 완료)")

        return pd.DataFrame(all_items)

    except Exception as e:
        logging.error(f"❌ XML 데이터 스트림 해석 중 예외 발생: {e}")
        return pd.DataFrame()


def preprocess_data(df):
    """2. 수치 데이터 정제 및 상태 라벨링 유틸 함수"""
    if df is None or df.empty:
        return pd.DataFrame()

    df['최대주차가능대수'] = pd.to_numeric(df['최대주차가능대수'], errors='coerce').fillna(0).astype(int)
    df['현재주차대수'] = pd.to_numeric(df['현재주차대수'], errors='coerce').fillna(0).astype(int)

    # 일부 주차장의 현재주차대수가 마이너스(-)로 들어오는 비정상 데이터 방어
    df['현재주차대수'] = df['현재주차대수'].clip(lower=0)

    # 빈 주차자리 수 재계산
    df['주차가능대수'] = df['최대주차가능대수'] - df['현재주차대수']
    df['주차가능대수'] = df['주차가능대수'].clip(lower=0)
    df['주차비율'] = (df['현재주차대수'] / df['최대주차가능대수']).fillna(0) * 100

    # 구 정보 쪼개기
    df['구'] = df['주차장명'].apply(lambda x: x.split()[0] if len(x.split()) > 0 else '기타구')

    # 상태 기준 적용
    def determine_status_and_color(row):
        avail = row['주차가능대수']
        if avail >= 10:
            return '충분', 'green'
        elif 3 <= avail <= 9:
            return '보통', 'blue'
        elif 1 <= avail <= 2:
            return '부족', 'orange'
        else:
            return '없음', 'red'

    status_series = df.apply(determine_status_and_color, axis=1)
    df['상태'] = [x[0] for x in status_series]
    df['마커색상'] = [x[1] for x in status_series]

    return df


def run_pipeline():
    """3. 통합 파이프라인 엔진 구동"""
    logging.info("=== 부산시 공영주차장 실시간 통합 파이프라인 가동 ===")

    if MY_API_KEY == "여기에_공공데이터포털_실제_인증키를_넣으세요":
        logging.error("❌ 에러: scheduler.py 상단의 MY_API_KEY 변수에 진짜 인증키를 입력하셔야 합니다!")
        return

    df_raw = fetch_all_stations()
    if df_raw is None or df_raw.empty:
        logging.warning("수집된 데이터가 비어있어 파일 저장을 건너뜁니다.")
        return

    df_processed = preprocess_data(df_raw)
    os.makedirs('data', exist_ok=True)

    # 대시보드(app.py) 연동 파일 저장
    df_processed.to_csv('data/car_latest.csv', index=False, encoding='utf-8-sig')

    now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    with open('data/last_updated.txt', 'w', encoding='utf-8') as f:
        f.write(now_str)

    logging.info(f"✔ [성공] {now_str} 기준 주차장 데이터 갱신 완료! (총 {len(df_processed)}개 적재됨)")


if __name__ == '__main__':
    scheduler = BlockingScheduler(timezone='Asia/Seoul')
    run_pipeline()
    scheduler.add_job(run_pipeline, 'interval', hours=1, id='xml_integrated_job')

    try:
        logging.info("정기 배치 스케줄러 루프 시작 (동작 주기: 1시간)")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logging.info("스케줄러가 정상적으로 종료되었습니다.")