import json

import streamlit as st
from openai import OpenAI
from pypdf import PdfReader
from supabase import create_client


st.set_page_config(
    page_title="AI 학습 정리 노트",
    page_icon="📘",
    layout="wide",
)

if "summary_result" not in st.session_state:
    st.session_state.summary_result = None
if "summary_document_id" not in st.session_state:
    st.session_state.summary_document_id = None
if "saved_summary_id" not in st.session_state:
    st.session_state.saved_summary_id = None
if "quiz_result" not in st.session_state:
    st.session_state.quiz_result = None


def get_supabase_client():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


def show_saved_summaries():
    st.subheader("저장된 요약")
    try:
        client = get_supabase_client()
        response = (
            client.table("summaries")
            .select("id, filename, summary, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        records = response.data or []
    except KeyError:
        st.error("Supabase 설정이 없습니다. secrets.toml에 SUPABASE_URL과 SUPABASE_KEY를 추가해 주세요.")
        return
    except Exception as error:
        st.error(f"저장 기록을 불러오는 중 오류가 발생했습니다: {error}")
        return

    if not records:
        st.info("저장된 요약이 없습니다.")
        return

    for record in records:
        summary = record.get("summary") or {}
        summary_text = str(summary.get("핵심 요약", "요약 내용이 없습니다."))
        preview = summary_text[:120]
        if len(summary_text) > 120:
            preview += "..."

        record_columns = st.columns([2, 2, 5, 1])
        with record_columns[0]:
            st.markdown(f"**{record.get('filename', '파일명 없음')}**")
        with record_columns[1]:
            st.caption(record.get("created_at", "저장 시각 없음"))
        with record_columns[2]:
            st.write(preview)
        with record_columns[3]:
            if st.button("삭제", key=f"delete_summary_{record['id']}"):
                try:
                    get_supabase_client().table("summaries").delete().eq(
                        "id", record["id"]
                    ).execute()
                    st.rerun()
                except Exception as error:
                    st.error(f"저장 기록을 삭제하는 중 오류가 발생했습니다: {error}")

        st.divider()

with st.sidebar:
    st.header("문서 업로드")
    uploaded_file = st.file_uploader(
        "PDF 파일 선택",
        type=["pdf"],
        accept_multiple_files=False,
        help="PDF 파일만 업로드할 수 있습니다.",
    )

    st.divider()
    st.subheader("문서 정보")

reader = None
page_count = 0
extracted_text = []
pdf_error = None

if uploaded_file is None:
    with st.sidebar:
        st.caption("업로드된 문서가 없습니다.")
else:
    try:
        reader = PdfReader(uploaded_file)
        page_count = len(reader.pages)
        document_id = f"{uploaded_file.name}:{uploaded_file.size}"
        if st.session_state.summary_document_id != document_id:
            st.session_state.summary_result = None
            st.session_state.saved_summary_id = None
            st.session_state.quiz_result = None
            st.session_state.summary_document_id = document_id

        with st.sidebar:
            st.caption("파일명")
            st.write(uploaded_file.name)
            st.metric("총 페이지 수", page_count)
    except Exception as error:
        pdf_error = error
        with st.sidebar:
            st.caption(uploaded_file.name)

st.title("AI 학습 정리 노트")
if uploaded_file is not None and reader is not None:
    st.write("업로드한 문서의 원문과 요약을 확인할 수 있습니다.")

original_tab, summary_tab, quiz_tab, records_tab = st.tabs(
    ["원문", "요약", "퀴즈", "저장 기록"]
)

with original_tab:
    if uploaded_file is None:
        st.info("사이드바에서 PDF 파일을 업로드해 주세요.")
    elif pdf_error is not None:
        st.error(f"PDF를 읽는 중 오류가 발생했습니다: {pdf_error}")
    else:
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or "(추출된 텍스트가 없습니다.)"
            extracted_text.append(page_text.strip())
            with st.expander(f"{page_number}페이지", expanded=page_number == 1):
                st.text_area(
                    f"{page_number}페이지 텍스트",
                    value=page_text.strip(),
                    height=260,
                    label_visibility="collapsed",
                )

with summary_tab:
    if uploaded_file is None or reader is None:
        st.info("PDF 파일을 업로드하면 요약할 수 있습니다.")
    else:
        st.subheader("문서 요약")
        if st.button("요약하기", type="primary"):
            try:
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                system_prompt = (
                    "당신은 학습 자료를 정리하는 도우미입니다. "
                    "사용자가 제공한 PDF 텍스트를 분석해 다음 형식의 JSON 객체로만 반환하세요. "
                    '"핵심 요약"은 정확히 3문장, '
                    '"주요 키워드"는 정확히 5개의 문자열 배열, '
                    '"난이도"는 반드시 "상", "중", "하" 중 하나여야 합니다. '
                    "마크다운이나 JSON 바깥의 설명은 포함하지 마세요."
                )
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": "다음 PDF 텍스트를 요약해 주세요.\n\n"
                            + "\n\n".join(extracted_text),
                        },
                    ],
                    response_format={"type": "json_object"},
                )
                st.session_state.summary_result = json.loads(
                    response.choices[0].message.content
                )
                st.session_state.quiz_result = None
                st.session_state.saved_summary_id = None
            except KeyError:
                st.error("OpenAI API 키가 설정되지 않았습니다. .streamlit/secrets.toml을 확인해 주세요.")
            except (json.JSONDecodeError, TypeError) as error:
                st.error(f"요약 결과를 JSON으로 읽는 중 오류가 발생했습니다: {error}")
            except Exception as error:
                st.error(f"요약 중 오류가 발생했습니다: {error}")

        if st.session_state.summary_result:
            summary_result = st.session_state.summary_result
            st.markdown("**핵심 요약**")
            st.write(summary_result.get("핵심 요약", "요약 내용이 없습니다."))
            st.markdown("**주요 키워드**")
            keywords = summary_result.get("주요 키워드", [])
            st.write(", ".join(str(keyword) for keyword in keywords))
            st.markdown("**난이도**")
            st.write(summary_result.get("난이도", "알 수 없음"))

            if st.button("저장"):
                try:
                    save_response = get_supabase_client().table("summaries").insert(
                        {
                            "filename": uploaded_file.name,
                            "summary": summary_result,
                            "quiz": None,
                        }
                    ).select("id").single().execute()
                    st.session_state.saved_summary_id = save_response.data["id"]
                    st.success("요약 결과를 저장했습니다.")
                except KeyError:
                    st.error("Supabase 설정이 없습니다. secrets.toml에 SUPABASE_URL과 SUPABASE_KEY를 추가해 주세요.")
                except Exception as error:
                    st.error(f"요약 결과를 저장하는 중 오류가 발생했습니다: {error}")

with quiz_tab:
    if uploaded_file is None or reader is None:
        st.info("PDF 파일을 업로드하면 퀴즈를 만들 수 있습니다.")
    elif not st.session_state.summary_result:
        st.info("먼저 요약 탭에서 요약을 만들어 주세요.")
    else:
        st.subheader("학습 퀴즈")
        if st.button("퀴즈 생성", type="primary"):
            try:
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                quiz_system_prompt = """당신은 학습 퀴즈를 만드는 도우미입니다.
주어진 요약을 바탕으로 4지선다 퀴즈 3문항을 만드세요.
각 문항은 question, options(4개), answer(정답 인덱스, 0부터 시작), explanation을 포함해야 합니다.
결과는 {"questions": [...]} 형태의 JSON으로 반환하세요.
"""
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": quiz_system_prompt},
                        {
                            "role": "user",
                            "content": "다음 요약만 사용해 퀴즈를 만들어 주세요.\n\n"
                            + json.dumps(
                                st.session_state.summary_result,
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    response_format={"type": "json_object"},
                )
                quiz_result = json.loads(response.choices[0].message.content)
                st.session_state.quiz_result = quiz_result

                if st.session_state.saved_summary_id is None:
                    st.info("퀴즈는 만들어졌습니다. 저장된 요약에 반영하려면 먼저 저장해주세요.")
                else:
                    get_supabase_client().table("summaries").update(
                        {"quiz": quiz_result}
                    ).eq("id", st.session_state.saved_summary_id).execute()
                    st.success("퀴즈를 저장된 요약에 반영했습니다.")
            except KeyError:
                st.error("OpenAI 또는 Supabase 설정이 없습니다. secrets.toml을 확인해 주세요.")
            except (json.JSONDecodeError, TypeError) as error:
                st.error(f"퀴즈 결과를 JSON으로 읽는 중 오류가 발생했습니다: {error}")
            except Exception as error:
                st.error(f"퀴즈를 생성하거나 저장하는 중 오류가 발생했습니다: {error}")

        if st.session_state.quiz_result:
            questions = st.session_state.quiz_result.get("questions", [])
            for question_number, question in enumerate(questions, start=1):
                st.markdown(f"### {question_number}. {question.get('question', '질문 없음')}")
                options = question.get("options", [])
                selected_option = st.radio(
                    "보기",
                    options,
                    index=None,
                    key=f"quiz_option_{question_number}",
                )
                if selected_option is not None:
                    selected_index = options.index(selected_option)
                    answer_index = int(question.get("answer", -1))
                    if selected_index == answer_index:
                        st.success("정답입니다.")
                    else:
                        st.error(f"오답입니다. 정답: {options[answer_index]}")
                    st.info(f"해설: {question.get('explanation', '해설이 없습니다.')}")

with records_tab:
    show_saved_summaries()
