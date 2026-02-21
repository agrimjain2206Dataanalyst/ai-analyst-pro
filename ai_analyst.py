# ai_analyst_pro_v2.py
# Fully upgraded AI Analyst Pro

import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime
import time
import re

# Optional libs
HAS_AGGRID = True
HAS_PYPDF2 = True
HAS_FPDF = True

try:
    from st_aggrid import AgGrid, GridOptionsBuilder
except Exception:
    HAS_AGGRID = False

try:
    from PyPDF2 import PdfReader
except Exception:
    HAS_PYPDF2 = False

try:
    from fpdf import FPDF
except Exception:
    HAS_FPDF = False

# Page config & dark CSS
st.set_page_config(page_title="AI Analyst Pro V2", layout="wide", page_icon="🤖")
st.markdown("""
<style>
.stApp { background-color: #0f1720; color: #e6eef8; }
.css-1d391kg { background-color: #0f1720; }
.st-bk { color: #e6eef8; }
</style>
""", unsafe_allow_html=True)

st.title("AI Analyst Pro V2 — by Agrim<3")
st.caption("Upload Excel/CSV/PDF, write a prompt, preview, undo/redo, get insights, pivot tables, charts, AI enrichment & download.")

# Sidebar
st.sidebar.header("Settings — Agrim's AI Analyst")
api_key = st.sidebar.text_input("Gemini/OpenAI API Key (user provides their key)", type="password", placeholder="Paste your API key here for AI tasks")
uploaded_file = st.sidebar.file_uploader("Upload Excel/CSV/PDF (Max ~10GB browser-friendly)", type=["xlsx","csv","pdf"])
prompt = st.sidebar.text_area("Prompt / Commands (e.g., drop duplicates, add column Profit=Revenue-Cost, summarize, pivot Sales by Product, chart Revenue)", height=150)
apply_btn = st.sidebar.button("Apply Prompt")
undo_btn = st.sidebar.button("Undo")
redo_btn = st.sidebar.button("Redo")
st.sidebar.markdown("---")
st.sidebar.markdown("Tip: For very large files, use disk path reading in advanced mode.")

# Session state
if "history" not in st.session_state: st.session_state.history=[]
if "redo_stack" not in st.session_state: st.session_state.redo_stack=[]
if "last_action_time" not in st.session_state: st.session_state.last_action_time=None

def push_history(df: pd.DataFrame):
    st.session_state.history.append(df.copy())
    if len(st.session_state.history)>30: st.session_state.history.pop(0)
    st.session_state.redo_stack=[]
    st.session_state.last_action_time=datetime.utcnow()

def can_undo(): return len(st.session_state.history)>1
def undo_action():
    if can_undo(): st.session_state.redo_stack.append(st.session_state.history.pop())
    return st.session_state.history[-1]
def redo_action():
    if st.session_state.redo_stack: st.session_state.history.append(st.session_state.redo_stack.pop())
    return st.session_state.history[-1]

# File reading
def read_uploaded_file(ufile):
    try: file_bytes = ufile.read()
    except: ufile.seek(0); file_bytes = ufile.read()
    fname = getattr(ufile,"name","uploaded").lower()
    if fname.endswith(".csv"):
        try: chunks=pd.read_csv(BytesIO(file_bytes),chunksize=200000); df=pd.concat(chunks,ignore_index=True)
        except: df=pd.read_csv(BytesIO(file_bytes))
    elif fname.endswith(".xlsx") or fname.endswith(".xls"):
        try: df=pd.read_excel(BytesIO(file_bytes),engine="openpyxl")
        except: df=pd.read_excel(BytesIO(file_bytes))
    elif fname.endswith(".pdf"):
        if not HAS_PYPDF2: st.warning("Install PyPDF2 for PDF extraction."); df=pd.DataFrame({"Text":[str(file_bytes[:1000])]})
        else:
            try:
                reader = PdfReader(BytesIO(file_bytes))
                pages = [p.extract_text() or "" for p in reader.pages]
                df = pd.DataFrame({"Text": pages})
            except: df=pd.DataFrame({"Text":[str(file_bytes[:1000])]})
    else: df=pd.DataFrame()
    df.columns=[str(c).strip() for c in df.columns]
    return df

# Prompt parser
def apply_prompt(df: pd.DataFrame, prompt_text: str):
    df = df.copy(); figs=[]
    if not prompt_text or not isinstance(prompt_text,str): return df, figs
    commands=[c.strip() for c in re.split(r",|;|\n",prompt_text) if c.strip()]

    for cmd in commands:
        low=cmd.lower()
        # Drop duplicates
        if "drop duplicates" in low: df=df.drop_duplicates()
        # Drop column
        m=re.search(r"drop column '?([\w _-]+)'?",low)
        if m: c1=m.group(1).strip(); df=df.drop(columns=[c1]) if c1 in df.columns else None
        # Fill missing
        m=re.search(r"fill\s+(?:missing|na|null)\s+in\s+([\w _-]+)\s+with\s+([\w .+-]+)",low)
        if m: c1, val = m.group(1), m.group(2); df[c1]=df[c1].fillna(float(val) if val.replace('.','',1).isdigit() else val) if c1 in df.columns else None
        # Convert column types
        m=re.search(r"convert\s+([\w _-]+)\s+to\s+(int|float|str|datetime)",low)
        if m:
            c1,dtype=m.group(1),m.group(2)
            try:
                df[c1] = pd.to_datetime(df[c1]) if dtype == "datetime" else df[c1].astype(dtype)
            except: pass
        # Sort
        m=re.search(r"sort by ([\w _-]+)(?:\s+(asc|desc))?",low)
        if m: col, order = m.group(1), m.group(2) or "asc"; df=df.sort_values(by=col,ascending=(order=="asc")) if col in df.columns else None
        # Add calculated column
        m=re.search(r"add column ([\w _-]+)=([\w _\+\-\*\/\(\)]+)",low)
        if m:
            col, expr = m.group(1), m.group(2)
            try: df[col]=df.eval(expr)
            except: pass
        # Summarize data
        if "summarize" in low:
            summary=pd.DataFrame({"Column":df.columns,"Non-Null":df.notnull().sum(),"Unique":df.nunique(),"Dtype":[str(t) for t in df.dtypes]})
            st.write("📊 Data Summary"); st.dataframe(summary)
        # Pivot Table
        m=re.search(r"pivot\s+([\w _-]+)\s+by\s+([\w _-]+)",low)
        if m:
            val_col, index_col = m.group(1), m.group(2)
            if val_col in df.columns and index_col in df.columns:
                pivot=pd.pivot_table(df,index=index_col,values=val_col,aggfunc=np.sum)
                st.write(f"📊 Pivot Table: {val_col} by {index_col}"); st.dataframe(pivot)
        # Chart (bar,line,pie)
        m=re.search(r"chart\s+([\w _-]+)\s+(bar|line|pie)",low)
        if m:
            col, chart_type = m.group(1), m.group(2)
            if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                if chart_type=="bar": st.bar_chart(df[col])
                elif chart_type=="line": st.line_chart(df[col])
                elif chart_type=="pie": st.write("Pie chart not directly supported; see dataframe above")
        # Answer question placeholder (requires AI)
        if "question:" in low and api_key:
            st.info(f"💡 Placeholder: AI will answer your question `{cmd}` if API key is valid")

    return df, figs

# Bytes for download
def df_to_bytes(df: pd.DataFrame, kind="excel"):
    if kind=="excel": towrite=BytesIO(); df.to_excel(towrite,index=False,engine="openpyxl"); towrite.seek(0); return towrite.getvalue()
    elif kind=="csv": return df.to_csv(index=False).encode("utf-8")
    elif kind=="pdf":
        if not HAS_FPDF: return None
        pdf=FPDF(); pdf.add_page(); pdf.set_font("Arial",10)
        for i,row in df.iterrows(): pdf.multi_cell(0,5,str(dict(row)))
        out=BytesIO(); pdf.output(out); out.seek(0); return out.getvalue()
    return None

# Main UI
placeholder=st.empty()
if not uploaded_file: placeholder.info("Upload a file — Agrim is ready ✨")
else:
    placeholder.info("Agrim is reviewing your file... ⏳"); time.sleep(0.3)
    try: df=read_uploaded_file(uploaded_file)
    except Exception as e: st.error(f"Failed: {e}"); df=pd.DataFrame()
    if not st.session_state.history: push_history(df)
    placeholder.success("Agrim loaded your file ✅")

    st.subheader("Preview — Before & After")
    left,right=st.columns([1,1])
    with left:
        st.markdown("**Before (current state)**") 
        if HAS_AGGRID:
            try: AgGrid(st.session_state.history[-1],fit_columns_on_grid_load=True,theme="dark",height=350)
            except: st.dataframe(st.session_state.history[-1].head(200))
        else: st.dataframe(st.session_state.history[-1].head(200))

    action_message=st.empty()
    if apply_btn:
        action_message.info("Agrim is applying your prompt... ⚡")
        with st.spinner("Processing..."):
            try: df_new, figs = apply_prompt(st.session_state.history[-1],prompt)
            except Exception as e: action_message.error(f"Failed: {e}"); df_new=st.session_state.history[-1].copy(); figs=[]
            push_history(df_new); action_message.success("Agrim applied your changes ✅"); st.session_state.last_action_time=datetime.utcnow()
            for f in figs: st.pyplot(f)
    if undo_btn:
        if can_undo(): _=undo_action(); action_message.info("Undo performed")
        else: action_message.warning("Nothing to undo")
    if redo_btn: _=redo_action(); action_message.info("Redo performed")

    with right:
        st.markdown("**After (latest state)**")
        if HAS_AGGRID:
            try: AgGrid(st.session_state.history[-1],fit_columns_on_grid_load=True,theme="dark",height=350)
            except: st.dataframe(st.session_state.history[-1].head(200))
        else: st.dataframe(st.session_state.history[-1].head(200))

    col_x,col_y,col_z=st.columns(3)
    with col_x:
        excel_bytes=df_to_bytes(st.session_state.history[-1],"excel")
        st.download_button("Download Excel (.xlsx)",data=excel_bytes,file_name="ai_analyst_cleaned.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with col_y:
        csv_bytes=df_to_bytes(st.session_state.history[-1],"csv")
        st.download_button("Download CSV (.csv)",data=csv_bytes,file_name="ai_analyst_cleaned.csv",mime="text/csv")
    with col_z:
        pdf_bytes=df_to_bytes(st.session_state.history[-1],"pdf")
        if pdf_bytes: st.download_button("Download PDF (.pdf)",data=pdf_bytes,file_name="ai_analyst_cleaned.pdf",mime="application/pdf")
        else: st.button("Install fpdf for PDF export")

    if st.session_state.last_action_time:
        st.markdown(f"*Last change: {st.session_state.last_action_time.strftime('%Y-%m-%d %H:%M:%S UTC')}*")

st.markdown("---")
st.markdown("**Missing features hints:**")
if not HAS_AGGRID: st.markdown("- Install: `pip install streamlit-aggrid`")
if not HAS_PYPDF2: st.markdown("- Install: `pip install PyPDF2`")
if not HAS_FPDF: st.markdown("- Install: `pip install fpdf`")
st.markdown("**Large files note:** Browser uploads may be limited. For multi-GB files, process from disk or use chunked CSV.")
