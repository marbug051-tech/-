import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import xml.etree.ElementTree as ET
import os
import numpy as np
import urllib.parse
from datetime import datetime

# =================================================================
# ⚙️ 고정 환경 변수 및 인증키 정의
# =================================================================
MY_API_KEY = "a5f9566584e40431a1de3aee64bc26344288646bf8328f502724b10f8883ec6c"
CSV_PATH = 'data/car_latest.csv'
TXT_PATH = 'data/last_updated.txt'

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="부산시 공영주차장 알리미",
    page_icon="🅿️",
    layout="wide"
)

if 'favorites' not in st.session_state:
    st.session_state['favorites'] = set()


# 💡 [행정구 분류] 키워드 기반 매핑
def assign_busan_gu(name):
    if any(k in name for k in ['노포', '부산대', '구서', '장전', '남산']): return '금정구'
    if any(k in name for k in
           ['반송', '장산', '좌1', '두산위브', '대우1차', '부산기계', '센텀', '반여', '동백', '중동', '미포', '해운대', '요트']): return '해운대구'
    if any(k in name for k in ['삼락', '학장천', '사상', '구남']): return '사상구'
    if any(k in name for k in ['수변어린이', '수변공원']): return '수영구'
    if any(k in name for k in ['동대신']): return '서구'
    if any(k in name for k in ['중앙공원', '광복']): return '중구'
    if any(k in name for k in ['신선', '영선']): return '영도구'
    if any(k in name for k in ['화명', '만덕']): return '북구'
    if any(k in name for k in ['하단']): return '사하구'
    if any(k in name for k in ['온천장', '명륜', '동래', '수안']): return '동래구'
    if any(k in name for k in ['부전', '적십자', '골드테마']): return '부산진구'
    if any(k in name for k in ['대연']): return '남구'
    return '기타구'


# 📍 [정밀 위경도 매핑] 네이버/카카오맵 연동용
def get_coords(name):
    mapping = {
        "반송": (35.2281, 129.1527), "삼락재첩": (35.1705, 128.9748), "수변어린이": (35.1539, 129.1256),
        "장산역 1": (35.1699, 129.1769), "장산역 2": (35.1702, 129.1765), "좌1": (35.1743, 129.1738),
        "노포": (35.2847, 129.0949), "두산위브": (35.1598, 129.1456), "대우1차": (35.1624, 129.1481),
        "부산기계": (35.1652, 129.1578), "센텀": (35.1689, 129.1309), "반여도서관": (35.1983, 129.1194),
        "동대신": (35.1132, 129.0203), "신선3": (35.0851, 129.0435), "영선": (35.0872, 129.0416),
        "동백": (35.1542, 129.1518), "중동이마트": (35.1668, 129.1672), "부산대역(남": (35.2285, 129.0888),
        "부산대역(북": (35.2307, 129.0898), "화명": (35.2363, 129.0139), "학장천": (35.1465, 128.9856),
        "수변공원": (35.1546, 129.1270), "중동역": (35.1667, 129.1673), "미포": (35.1601, 129.1724),
        "온천장": (35.2202, 129.0864), "구서": (35.2474, 129.0913), "중앙공원": (35.1114, 129.0308),
        "장전": (35.2381, 129.0881), "사상역": (35.1625, 128.9830), "남산": (35.2651, 129.0924),
        "하단": (35.1061, 128.9667), "명륜": (35.2125, 129.0796), "동래": (35.2057, 129.0784),
        "해운대광장": (35.1630, 129.1630), "광복": (35.0991, 129.0362), "반여2": (35.1995, 129.1221),
        "요트경기장 앞 1": (35.1620, 129.1380), "삼락천": (35.1685, 128.9770), "부전복개도로1": (35.1555, 129.0560),
        "부전복개도로2": (35.1570, 129.0558), "적십자": (35.1618, 129.0622), "대연": (35.1375, 129.0915),
        "골드테마": (35.1402, 129.0605), "요트경기장 앞 2": (35.1610, 129.1385), "수안동": (35.2020, 129.0830),
        "구남": (35.2070, 128.9984), "만덕": (35.2105, 129.0302)
    }
    for key, coords in mapping.items():
        if key in name:
            return coords
    return (35.1796 + np.random.uniform(-0.02, 0.02), 129.0756 + np.random.uniform(-0.02, 0.02))


# ⚡ [전기차 충전소 인프라 매핑]
EV_SUPPORTED_LOTS = [
    "노포역", "해운대 센텀시티", "부산대역(남측)", "부산대역(북측)", "화명역",
    "수변공원", "온천장역(남측)", "구서역", "장전역", "사상역 광장", "남산역",
    "하단역", "명륜역", "동래역", "요트경기장 앞 1구역", "수안동주차빌딩", "장산역 1번"
]


# 📡 [실시간 API 수집 및 전처리]
def force_refresh_live_data():
    base_url = "http://apis.data.go.kr/B552587/ParkingInfoService_v2/getParkingInfoList_v2"
    params = {'serviceKey': MY_API_KEY, 'pageNo': 1, 'numOfRows': 1000, '_type': 'json'}

    try:
        response = requests.get(base_url, params=params, timeout=15)
        root = ET.fromstring(response.text.strip())
        items_node = root.find('.//items')

        if items_node is None: return False

        all_items = []
        now = datetime.now()
        for item_node in items_node.findall('item'):
            park_name = item_node.findtext('parknm', '이름 없음')
            max_cnt = int(item_node.findtext('maxcnt', '0'))
            park_cnt = int(item_node.findtext('parkingcnt', '0'))

            cur_avail = int(item_node.findtext('curravacnt', '0'))
            avail_cnt = max(0, cur_avail)

            park_cnt = max(0, park_cnt)
            ratio = (park_cnt / max_cnt * 100) if max_cnt > 0 else 0.0

            if avail_cnt >= 10:
                status, color = '충분', 'green'
            elif 3 <= avail_cnt <= 9:
                status, color = '보통', 'blue'
            elif 1 <= avail_cnt <= 2:
                status, color = '부족', 'orange'
            else:
                status, color = '없음', 'red'

            ev_status = True if park_name in EV_SUPPORTED_LOTS else False
            lat, lng = get_coords(park_name)

            all_items.append({
                '주차장명': park_name,
                '최대주차가능대수': max_cnt,
                '현재주차대수': park_cnt,
                '주차가능대수': avail_cnt,
                '주차비율': ratio,
                '최종갱신일시': item_node.findtext('lastupdatetime', now.strftime('%Y-%m-%d %H:%M:%S')),
                '구': assign_busan_gu(park_name),
                '상태': status,
                '전기차충전': ev_status,
                '위도': lat,
                '경도': lng
            })

        if all_items:
            df = pd.DataFrame(all_items)
            os.makedirs('data', exist_ok=True)
            df.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')

            with open(TXT_PATH, 'w', encoding='utf-8') as f:
                f.write(now.strftime('%Y-%m-%d %H:%M:%S'))
            return True
    except Exception as e:
        st.sidebar.error(f"갱신 실패: {e}")
    return False


# 2. 데이터 로드 함수 (오류 방어 로직 추가)
@st.cache_data(ttl=60)
def load_saved_data():
    if not os.path.exists(CSV_PATH):
        force_refresh_live_data()
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        if '주차장명' in df.columns:
            df['구'] = df['주차장명'].apply(assign_busan_gu)

            # 옛날 CSV 파일에 전기차/위도/경도 데이터가 없으면 강제로 채워넣음 (KeyError 방지)
            if '전기차충전' not in df.columns:
                df['전기차충전'] = df['주차장명'].apply(lambda x: True if x in EV_SUPPORTED_LOTS else False)
            if '위도' not in df.columns or '경도' not in df.columns:
                coords = df['주차장명'].apply(get_coords)
                df['위도'] = [c[0] for c in coords]
                df['경도'] = [c[1] for c in coords]

        return df
    return pd.DataFrame()


df_origin = load_saved_data()

last_updated = "미정"
if os.path.exists(TXT_PATH):
    with open(TXT_PATH, 'r', encoding='utf-8') as f:
        last_updated = f.read().strip()

# ==========================================
# 🛠️ 사이드바 구성
# ==========================================
st.sidebar.header("📋 메뉴")
page = st.sidebar.radio(
    "이동할 화면",
    ["⭐ 내 관심 주차장", "1. 주차장 현황 분석", "2. 실시간 주차장 찾기", "3. 행정구별 주차장 현황", "4. 빠른 추천"]
)

st.sidebar.write("---")
st.sidebar.header("🔍 필터링 검색")

search_query = st.sidebar.text_input("주차장명 검색", placeholder="키워드 입력")
show_only_available = st.sidebar.checkbox("주차 가능한 주차장만 보기", value=True)
show_only_ev = st.sidebar.checkbox("⚡ 전기차 충전 가능한 곳만 보기", value=False)
sort_option = st.sidebar.selectbox("정렬 기준", ["주차가능한 자리많은 순", "이름순", "주차된 차 비율 낮은 순"])

if st.sidebar.button("🔄 실시간 새로고침"):
    with st.sidebar.spinner("API 데이터 최신화 중..."):
        if force_refresh_live_data():
            st.sidebar.success("동기화 완료!")
            st.cache_data.clear()
            st.rerun()

st.sidebar.write("---")

st.sidebar.header("💰 주차 요금 계산기")
park_class = st.sidebar.selectbox(
    "공영주차장 급지 선택",
    ["1급지 (번화가/도심)", "2급지 (일반상업지역)", "3급지 (주거/외곽)", "4급지 (변두리)"]
)
park_time = st.sidebar.number_input("예상 주차 시간 (분)", min_value=10, max_value=1440, step=10, value=60)

fee_map = {"1급지 (번화가/도심)": 500, "2급지 (일반상업지역)": 300, "3급지 (주거/외곽)": 200, "4급지 (변두리)": 100}
cost_per_10m = fee_map[park_class]
total_fee = (park_time // 10) * cost_per_10m

st.sidebar.info(f"**💡 예상 요금: {total_fee:,}원**\n\n*(10분당 {cost_per_10m}원 기준)*")
st.sidebar.caption(f"최종 갱신: {last_updated}")

if df_origin.empty:
    st.error("데이터 로드 실패.")
    st.stop()

# 필터 적용
df_filtered = df_origin.copy()
if search_query:
    df_filtered = df_filtered[df_filtered['주차장명'].str.contains(search_query, case=False, na=False)]
if show_only_available:
    df_filtered = df_filtered[df_filtered['주차가능대수'] > 0]
if show_only_ev:
    df_filtered = df_filtered[df_filtered['전기차충전'] == True]

if sort_option == "주차가능한 자리많은 순":
    df_filtered = df_filtered.sort_values(by='주차가능대수', ascending=False)
elif sort_option == "이름순":
    df_filtered = df_filtered.sort_values(by='주차장명', ascending=True)
elif sort_option == "주차된 차 비율 낮은 순":
    df_filtered = df_filtered.sort_values(by='주차비율', ascending=True)

status_colors = {'충분': '#2E7D32', '보통': '#1565C0', '부족': '#EF6C00', '없음': '#C62828'}


# ⭐ 주차장 카드 렌더링 함수 (전기차 뱃지 + 원클릭 길찾기 추가)
def draw_parking_card(row, page_key):
    with st.container(border=True):
        st.markdown(f"#### **{row['주차장명']}**")

        ev_badge = "<span style='background-color:#E8F5E9; color:#2E7D32; padding:3px 8px; border-radius:12px; font-size:13px; font-weight:bold; border: 1px solid #A5D6A7;'>⚡ EV충전소</span>" if \
        row['전기차충전'] else ""
        txt_color = status_colors.get(row['상태'], '#333333')

        st.markdown(f"🏙️ 소속 구: <b style='font-size: 19px;'>{row['구']}</b> &nbsp; {ev_badge}", unsafe_allow_html=True)
        st.markdown(f"🚦 상태: <b style='font-size: 21px; color: {txt_color};'>{row['상태']}</b>", unsafe_allow_html=True)
        st.write(f"• 전체 주차 대수: {row['최대주차가능대수']}대")
        st.write(f"• 주차된 차: {row['현재주차대수']}대")
        st.markdown(f"• **현재 빈자리: {row['주차가능대수']}대**")

        is_fav = row['주차장명'] in st.session_state['favorites']
        btn_label = "❤️ 즐겨찾기 취소" if is_fav else "🤍 즐겨찾기 추가"

        # 관심 주차장 버튼
        if st.button(btn_label, key=f"fav_{row['주차장명']}_{page_key}"):
            if is_fav:
                st.session_state['favorites'].remove(row['주차장명'])
            else:
                st.session_state['favorites'].add(row['주차장명'])
            st.rerun()

        st.write("---")

        # 🧭 원클릭 내비게이션 버튼 나란히 배치
        nav_col1, nav_col2 = st.columns(2)
        safe_name = urllib.parse.quote(row['주차장명'] + " 공영주차장")

        with nav_col1:
            kakao_url = f"https://map.kakao.com/link/to/{safe_name},{row['위도']},{row['경도']}"
            st.link_button("🚙 카카오 길찾기", kakao_url, use_container_width=True)
        with nav_col2:
            naver_url = f"https://map.naver.com/v5/search/{safe_name}"
            st.link_button("🧭 네이버 지도", naver_url, use_container_width=True)


# ==========================================
# 🖥️ 메인 렌더링
# ==========================================
st.title("🅿️ 부산시 공영주차장 알리미")
st.write("---")

if page == "⭐ 내 관심 주차장":
    st.markdown("### ❤️ 내가 즐겨찾기한 주차장 모아보기")
    fav_df = df_filtered[df_filtered['주차장명'].isin(st.session_state['favorites'])]
    if fav_df.empty:
        st.info("아직 관심 주차장이 없습니다. 다른 탭에서 🤍 버튼을 눌러 추가해 보세요!")
    else:
        cols = st.columns(3)
        for idx, row in fav_df.reset_index().iterrows():
            with cols[idx % 3]: draw_parking_card(row, "fav_page")

elif page == "1. 주차장 현황 분석":
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("조회된 주차장", f"{len(df_filtered)} 개")
    col2.metric("전체 주차 대수", f"{df_filtered['현재주차대수'].sum():,} 대")
    col3.metric("평균 잔여석", f"{df_filtered['주차가능대수'].mean():.1f} 대" if len(df_filtered) > 0 else "0 대")
    col4.metric("자리 없는 곳(🔴)", f"{len(df_filtered[df_filtered['상태'] == '없음'])} 개")
    col5.metric("자리 충분한 곳(🟢)", f"{len(df_filtered[df_filtered['상태'] == '충분'])} 개")

    st.write("---")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 주차 가능 비율", "🏢 지역별 주차 가능 현황", "🏆 TOP 10 주차장", "⚠️ 혼잡 현황"])
    with tab1:
        fig = px.pie(df_filtered['상태'].value_counts().reset_index(), values='count', names='상태', hole=0.4,
                     color='상태', color_discrete_map={'충분': 'green', '보통': 'blue', '부족': 'orange', '없음': 'red'})
        st.plotly_chart(fig, use_container_width=True)
    with tab2:
        gu_df = df_filtered.groupby('구')['주차가능대수'].mean().reset_index().sort_values(by='주차가능대수', ascending=False)
        fig = px.bar(gu_df, x='구', y='주차가능대수', color='주차가능대수', color_continuous_scale=px.colors.sequential.Teal,
                     text_auto='.1f')
        st.plotly_chart(fig, use_container_width=True)
    with tab3:
        top10 = df_filtered.sort_values(by='주차가능대수', ascending=False).head(10)
        fig = px.bar(top10, x='주차가능대수', y='주차장명', orientation='h', color='주차가능대수',
                     color_continuous_scale=px.colors.sequential.Blues)
        fig.update_layout(yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)
    with tab4:
        st.dataframe(df_filtered[df_filtered['상태'].isin(['부족', '없음'])][['주차장명', '구', '최대주차가능대수', '주차가능대수', '상태']],
                     use_container_width=True)

elif page == "2. 실시간 주차장 찾기":
    st.markdown("### 🔍 실시간 주차장 카드")
    if df_filtered.empty:
        st.info("조건에 일치하는 주차장 정보가 존재하지 않습니다.")
    else:
        cols = st.columns(3)
        for idx, row in df_filtered.reset_index().iterrows():
            with cols[idx % 3]: draw_parking_card(row, "all_page")

elif page == "3. 행정구별 주차장 현황":
    st.markdown("### 🏢 행정구역별 카드")
    gus = sorted(df_filtered['구'].unique())
    if not gus:
        st.warning("선택할 행정구가 없습니다.")
    else:
        selected_gu = st.selectbox("📍 행정구 선택", gus)
        target_df = df_filtered[df_filtered['구'] == selected_gu]
        st.write("---")
        if target_df.empty:
            st.info(f"{selected_gu} 지역에 주차 가능한 곳이 없습니다.")
        else:
            cols = st.columns(3)
            for idx, row in target_df.reset_index().iterrows():
                with cols[idx % 3]: draw_parking_card(row, "gu_page")

elif page == "4. 빠른 추천":
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### ✅ 주차하기 좋은 곳 TOP 10")
        st.dataframe(df_origin.sort_values(by='주차가능대수', ascending=False).head(10)[['주차장명', '구', '주차가능대수', '전기차충전']],
                     use_container_width=True)

        st.markdown("#### ⚠️ 자리 부족 (1~2대)")
        st.dataframe(df_origin[df_origin['상태'] == '부족'][['주차장명', '구', '주차가능대수']], use_container_width=True)
    with c2:
        st.markdown("#### 🏢 규모 깡패 TOP 10 (총 면수)")
        st.dataframe(df_origin.sort_values(by='최대주차가능대수', ascending=False).head(10)[['주차장명', '최대주차가능대수', '주차가능대수']],
                     use_container_width=True)

        st.markdown("#### 🚨 만차 (자리 없음)")
        st.dataframe(df_origin[df_origin['상태'] == '없음'][['주차장명', '구', '최대주차가능대수']], use_container_width=True)