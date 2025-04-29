import streamlit as st
import yfinance as yf
from datetime import datetime
from fpdf import FPDF
import os
import duediligenceprompt as prompt
import PyPDF2

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.projects.models import (
    CodeInterpreterTool, BingGroundingTool, FilePurpose, ToolSet
)
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

AZUREML_CONN_STR = os.getenv("AZUREML_CONN_STR")
BING_CONNECTION_NAME = os.getenv("BING_CONNECTION_NAME")

def safe_latin1(text):
    replacements = {
        '’': "'",
        '‘': "'",
        '“': '"',
        '”': '"',
        '–': '-',
        '—': '-',
        '•': '-',
        '…': '...',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode('latin-1', 'ignore').decode('latin-1')

class CustomFPDF(FPDF):
    def multi_cell_bold(self, w, h, txt, align='L'):
        # If line contains '##', make it bold, else normal
        if "##" in txt:
            self.set_font("Arial", 'B', 10)
            self.multi_cell(w, h, txt.replace("##", "").strip(), align)
            self.set_font("Arial", '', 10)
        elif "**" in txt:
            self.set_font("Arial", 'B', 8)
            self.multi_cell(w, h, txt.replace("**", "").strip(), align)
            self.set_font("Arial", '', 8)
        else:
            self.multi_cell(w, h, txt, align)

# Move title 15% above and decrease font size a bit
st.markdown(
    """
    <div style="position: relative; top: -15%; font-size:1.3rem; font-weight:600;">
        Vendor Due Diligence Report
    </div>
    """,
    unsafe_allow_html=True
)
st.write("This agent generates initial due diligence report for a given company or stock ticker.")

# --- State management ---
if "pdf_generated" not in st.session_state:
    st.session_state["pdf_generated"] = False
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "pdf_text" not in st.session_state:
    st.session_state["pdf_text"] = ""
if "pdf_filename" not in st.session_state:
    st.session_state["pdf_filename"] = ""
if "chart_img" not in st.session_state:
    st.session_state["chart_img"] = None
if "final_analysis" not in st.session_state:
    st.session_state["final_analysis"] = ""
if "comprehensive_done" not in st.session_state:
    st.session_state["comprehensive_done"] = False
if "cmpr_pdf_filename" not in st.session_state:
    st.session_state["cmpr_pdf_filename"] = ""
if "cmpr_analysis" not in st.session_state:
    st.session_state["cmpr_analysis"] = ""
if "all_charts" not in st.session_state:
    st.session_state["all_charts"] = []

# --- UI controls ---
company_input = st.text_input("Enter Company Name or Stock Ticker (e.g., Microsoft or MSFT)", value="MSFT")
start_date_str = st.date_input("Start Date", value=datetime(2024, 6, 1))
end_date_str = st.date_input("End Date", value=datetime.today())

# --- Button Row ---
col1, col2, col3 = st.columns([1, 1, 2])

with col1:
    pdf_path = st.session_state.get("pdf_filename")
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            st.download_button(
                label="Download PDF",
                data=f,
                file_name=pdf_path,
                mime="application/pdf"
            )
    else:
        st.download_button(
            label="Download PDF",
            data=b"",
            file_name="",
            mime="application/pdf",
            disabled=False
        )

with col2:
    if st.button("Clear"):
        if st.session_state.get("all_charts"):
            for chart_img in st.session_state["all_charts"]:
                if chart_img and os.path.exists(chart_img):
                    os.remove(chart_img)
        if st.session_state.get("chart_img") and os.path.exists(st.session_state["chart_img"]):
            os.remove(st.session_state["chart_img"])
        for key in [
            "pdf_generated", "chat_history", "pdf_text", "pdf_filename",
            "chart_img", "final_analysis", "comprehensive_done", "cmpr_pdf_filename",
            "cmpr_analysis", "all_charts"
        ]:
            if key in st.session_state:
                del st.session_state[key]
        st.experimental_rerun()

with col3:
    generate_clicked = st.button("Generate Due Diligence Report", key="generate_due_diligence")

def resolve_ticker(company_or_ticker):
    data = yf.Ticker(company_or_ticker)
    hist = data.history(period="1d")
    if not hist.empty:
        return company_or_ticker
    try:
        project_client = AIProjectClient.from_connection_string(
            credential=DefaultAzureCredential(),
            conn_str=AZUREML_CONN_STR
        )
        bing_connection = project_client.connections.get(connection_name=BING_CONNECTION_NAME)
        conn_id = bing_connection.id
        bing_tool = BingGroundingTool(connection_id=conn_id)
        toolset = ToolSet()
        toolset.add(bing_tool)
        agent = project_client.agents.create_agent(
            model="gpt-4o",
            name="ticker-resolver",
            instructions=(
                "You are a financial assistant. Given a company name, respond ONLY with the official US stock ticker symbol from NYSE. "
                "If company_or_ticker name is Microsoft, respond with MSFT. "
                "If company_or_ticker name is Apple, respond with AAPL. "
                "Don't include any other information. "
                "If you cannot find a ticker, respond with 'NOTICKER'."
            ),
            toolset=toolset
        )
        thread = project_client.agents.create_thread()
        project_client.agents.create_message(
            thread_id=thread.id,
            role="user",
            content=f"What is the official US stock ticker for {company_or_ticker}?",
        )
        project_client.agents.create_and_process_run(thread_id=thread.id, agent_id=agent.id)
        messages = project_client.agents.list_messages(thread_id=thread.id)
        ticker = None
        for msg in messages['data']:
            if msg['role'] == 'assistant':
                for content in msg['content']:
                    if content['type'] == 'text':
                        val = content['text']['value'].strip().upper()
                        if val and val != "NOTICKER":
                            ticker = val.split()[0].replace('.', '-')
                        break
        project_client.agents.delete_agent(agent.id)
        project_client.agents.delete_thread(thread.id)
        return ticker
    except Exception:
        return None

def answer_query(pdf_text, user_query):
    try:
        project_client = AIProjectClient.from_connection_string(
            credential=DefaultAzureCredential(),
            conn_str=AZUREML_CONN_STR
        )
        instructions = (
            "You are an expert assistant that answers questions based on the provided PDF content. "
            "Use the context from the PDF to provide a precise answer."
            f"\nHere is the PDF content:\n{pdf_text}\n"
            f"\nQuestion: {user_query}"
        )
        agent = project_client.agents.create_agent(
            model="gpt-4o",
            name="pdf-chat-agent",
            instructions=instructions,
            toolset=ToolSet()
        )
        thread = project_client.agents.create_thread()
        project_client.agents.create_message(
            thread_id=thread.id,
            role="user",
            content=user_query,
        )
        project_client.agents.create_and_process_run(thread_id=thread.id, agent_id=agent.id)
        messages = project_client.agents.list_messages(thread_id=thread.id)
        answer = ""
        for msg in messages['data']:
            if msg['role'] == 'assistant':
                for content in msg['content']:
                    if content['type'] == 'text':
                        answer = content['text']['value']
                        break
                if answer:
                    break
        project_client.agents.delete_agent(agent.id)
        project_client.agents.delete_thread(thread.id)
        return answer
    except Exception as e:
        return f"Error retrieving answer: {str(e)}"

def chat_with_pdf():
    with st.sidebar:
        st.subheader("Chat with Generated Due Diligence Report")
        st.write("Ask questions about the PDF content.")
        with st.form(key="chat_form", clear_on_submit=True):
            user_query = st.text_input("Ask a question about the PDF", key="chat_input")
            submitted = st.form_submit_button(label="Send")
            if submitted and user_query:
                # Use both analyses if comprehensive is done
                pdf_text = st.session_state["final_analysis"]
                if st.session_state.get("comprehensive_done", False) and st.session_state.get("cmpr_analysis"):
                    pdf_text += "\n\n---\n\n" + st.session_state["cmpr_analysis"]
                answer = answer_query(pdf_text, user_query)
                st.session_state["chat_history"].append((user_query, answer))
        if st.session_state["chat_history"]:
            for q, a in st.session_state["chat_history"]:
                st.write("**Q:** " + q)
                st.write("**A:** " + a)

def comprehensive_due_diligence(
    ticker, start_date_str, end_date_str, prev_analysis, csv_filename, prev_pdf_filename, prev_charts
):
    project_client = AIProjectClient.from_connection_string(
        credential=DefaultAzureCredential(),
        conn_str=AZUREML_CONN_STR
    )
    file = project_client.agents.upload_file_and_poll(
        file_path=csv_filename, purpose=FilePurpose.AGENTS
    )
    code_interpreter = CodeInterpreterTool(file_ids=[file.id])
    bing_connection = project_client.connections.get(connection_name=BING_CONNECTION_NAME)
    conn_id = bing_connection.id
    bing_tool = BingGroundingTool(connection_id=conn_id)
    toolset = ToolSet()
    toolset.add(bing_tool)
    toolset.add(code_interpreter)
    instructions = (
        "You are a senior financial analyst. "
        "Perform a comprehensive due diligence for the company, including broad market conditions, cashflows, debt, and liquidity. "
        "Use Bing and all available market information. "
        "If information is not available, say so. "
        "Conclude if due diligence is passed or failed, and explain why. "
        "Summarize findings in markdown and tabular format. "
        "Include any charts or tables as needed. "
        f"Company: {ticker}\nPeriod: {start_date_str} to {end_date_str}\n"
        "Here is the previous analysis for context:\n"
        f"{prev_analysis}\n"
        f"Use the uploaded file {csv_filename} for financial data."
        "Mandatorily, conclude if due diligence is passed or failed. "
    )
    agent = project_client.agents.create_agent(
        model="gpt-4o",
        name="comprehensive-agent",
        instructions=instructions,
        toolset=toolset
    )
    thread = project_client.agents.create_thread()
    project_client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=f"Do a comprehensive due diligence for {ticker} from {start_date_str} to {end_date_str}.",
    )
    project_client.agents.create_and_process_run(thread_id=thread.id, agent_id=agent.id)
    messages = project_client.agents.list_messages(thread_id=thread.id)
    comp_analysis_list = []
    for msg in messages['data']:
        if msg['role'] == 'assistant':
            for content in msg['content']:
                if content['type'] == 'text':
                    comp_analysis_list.append(content['text']['value'])
    comp_analysis = "\n\n".join(comp_analysis_list)
    # Collect all charts: previous + new
    all_charts = prev_charts.copy() if prev_charts else []
    if hasattr(messages, "image_contents"):
        for image_content in messages.image_contents:
            chart_img = f"{image_content.image_file.file_id}_image_file.png"
            project_client.agents.save_file(file_id=image_content.image_file.file_id, file_name=chart_img)
            all_charts.append(chart_img)
            st.session_state["chart_img"] = chart_img
            break
    project_client.agents.delete_agent(agent.id)
    project_client.agents.delete_thread(thread.id)
    prev_pdf_basename = os.path.basename(prev_pdf_filename)
    cmpr_pdf_filename = f"cmprhsive_{prev_pdf_basename}"
    pdf = CustomFPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    page_width = pdf.w - 2 * pdf.l_margin
    line_height = 6
    # Add previous analysis and new comprehensive analysis
    for line in prev_analysis.split('\n'):
        pdf.multi_cell_bold(page_width, line_height, txt=safe_latin1(line), align='L')
    pdf.multi_cell_bold(page_width, line_height, txt=safe_latin1("\n---\n"), align='L')
    for line in comp_analysis.split('\n'):
        pdf.multi_cell_bold(page_width, line_height, txt=safe_latin1(line), align='L')
    # Add all charts (previous + new)
    for chart_img in all_charts:
        if chart_img and os.path.exists(chart_img):
            pdf.image(chart_img, x=10, y=pdf.get_y(), w=page_width-20)
    pdf.output(cmpr_pdf_filename)
    return comp_analysis, all_charts, cmpr_pdf_filename

# --- Main logic ---
if generate_clicked and not st.session_state.get("pdf_generated", False):
    ticker = resolve_ticker(company_input.strip())
    st.write(f"Resolved Ticker: {ticker}")
    if not ticker:
        st.error("Could not resolve a valid ticker symbol for your input. Please check the company name or ticker.")
    else:
        data = yf.download(ticker, start=start_date_str, end=end_date_str)
        if data.empty:
            st.error(f"No data found for ticker: {ticker} in the given date range.")
        else:
            analysis = []
            analysis.append(f"**Ticker:** {ticker}")
            analysis.append(f"**Period:** {start_date_str} to {end_date_str}")

            if len(data['Close']) > 1:
                try:
                    start_price = float(data['Close'].iloc[0])
                    end_price = float(data['Close'].iloc[-1])
                    change = ((end_price - start_price) / start_price) * 100
                    volatility = data['Close'].std()
                    if hasattr(volatility, '__len__'):
                        volatility = float(volatility.iloc[0])
                    else:
                        volatility = float(volatility)
                    analysis.append(f"**Start Price:** {start_price:.2f} USD")
                    analysis.append(f"**End Price:** {end_price:.2f} USD")
                    analysis.append(f"**Change:** {change:.2f}%")
                    analysis.append(f"**Volatility (std dev):** {volatility:.2f}")
                except Exception as e:
                    analysis.append("Error calculating analysis: " + str(e))
            else:
                analysis.append("Not enough data to generate analysis for the selected period.")

            csv_filename = f"{ticker}_{start_date_str}_to_{end_date_str}.csv"
            data.to_csv(csv_filename)

            project_client = AIProjectClient.from_connection_string(
                credential=DefaultAzureCredential(),
                conn_str=AZUREML_CONN_STR
            )
            file = project_client.agents.upload_file_and_poll(
                file_path=csv_filename, purpose=FilePurpose.AGENTS
            )
            code_interpreter = CodeInterpreterTool(file_ids=[file.id])
            bing_connection = project_client.connections.get(connection_name=BING_CONNECTION_NAME)
            conn_id = bing_connection.id
            bing_tool = BingGroundingTool(connection_id=conn_id)
            toolset = ToolSet()
            toolset.add(bing_tool)
            toolset.add(code_interpreter)
            instructions = prompt.instructions + f"Use file {csv_filename} having {file.id} to get more data. "
            instructions += "Do market research and use the uploaded file to compulsorily provide due diligence report. "
            agent = project_client.agents.create_agent(
                model="gpt-4o",
                name="due diligince agent",
                instructions=instructions,
                toolset=toolset
            )
            thread = project_client.agents.create_thread()
            project_client.agents.create_message(
                thread_id=thread.id,
                role="user",
                content=f"Could you please create chart of the stock mentioned {ticker} from {start_date_str} to {end_date_str}?",
            )
            project_client.agents.create_and_process_run(thread_id=thread.id, agent_id=agent.id)
            messages = project_client.agents.list_messages(thread_id=thread.id)
            agent_analysis_list = []
            for msg in messages['data']:
                if msg['role'] == 'assistant':
                    for content in msg['content']:
                        if content['type'] == 'text':
                            agent_analysis_list.append(content['text']['value'])
            agent_analysis = "\n\n".join(agent_analysis_list)

            final_analysis = "\n".join(analysis) + ("\n\n" + agent_analysis if agent_analysis else "")
            st.session_state["final_analysis"] = final_analysis

            pdf_filename = f"{ticker}_{start_date_str}_to_{end_date_str}_analysis.pdf"
            pdf = CustomFPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=10)
            page_width = pdf.w - 2 * pdf.l_margin
            line_height = 6

            for line in analysis:
                pdf.multi_cell_bold(page_width, line_height, txt=safe_latin1(line), align='L')
            if agent_analysis:
                for line in agent_analysis.split('\n'):
                    pdf.multi_cell_bold(page_width, line_height, txt=safe_latin1(line), align='L')

            chart_img = None
            all_charts = []
            if hasattr(messages, "image_contents"):
                for image_content in messages.image_contents:
                    chart_img = f"{image_content.image_file.file_id}_image_file.png"
                    project_client.agents.save_file(file_id=image_content.image_file.file_id, file_name=chart_img)
                    st.session_state["chart_img"] = chart_img
                    all_charts.append(chart_img)
                    pdf.image(chart_img, x=10, y=pdf.get_y(), w=page_width-20)
                    break

            pdf.output(pdf_filename)
            st.success("PDF generated successfully.")
            st.session_state["pdf_filename"] = pdf_filename
            st.session_state["all_charts"] = all_charts

            project_client.agents.delete_agent(agent.id)
            project_client.agents.delete_thread(thread.id)

            with open(pdf_filename, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                pdf_text = ""
                for page in reader.pages:
                    pdf_text += page.extract_text() + "\n"
            st.session_state["pdf_text"] = pdf_text
            st.session_state["pdf_generated"] = True
            st.session_state["comprehensive_done"] = False
            st.session_state["cmpr_pdf_filename"] = ""
            st.session_state["cmpr_analysis"] = ""

# Always show Comprehensive Due Diligence PDF button if available
cmpr_pdf_path = st.session_state.get("cmpr_pdf_filename")
if cmpr_pdf_path and os.path.exists(cmpr_pdf_path):
    with open(cmpr_pdf_path, "rb") as f:
        st.download_button(
            label="Comprehensive Due Diligence PDF",
            data=f,
            file_name=cmpr_pdf_path,
            mime="application/pdf"
        )

# Always show outputs and chat if PDF is available
if st.session_state.get("pdf_generated", False):
    # Chart
    if st.session_state.get("all_charts"):
        for chart_img in st.session_state["all_charts"]:
            if chart_img and os.path.exists(chart_img):
                st.image(chart_img, caption="Stock Price Chart", use_container_width=True)
    elif st.session_state.get("chart_img") and os.path.exists(st.session_state["chart_img"]):
        st.image(st.session_state["chart_img"], caption="Stock Price Chart", use_container_width=True)
    # Analysis
    st.text_area("Final Analysis", st.session_state.get("final_analysis", ""), height=250)
    # Comprehensive Due Diligence Button
    if not st.session_state.get("comprehensive_done", False):
        if st.button("Comprehensive Due Diligence"):
            ticker = resolve_ticker(company_input.strip())
            csv_filename = f"{ticker}_{start_date_str}_to_{end_date_str}.csv"
            prev_pdf_filename = st.session_state.get("pdf_filename", "")
            prev_charts = st.session_state.get("all_charts", [])
            comp_analysis, all_charts, cmpr_pdf_filename = comprehensive_due_diligence(
                ticker, start_date_str, end_date_str, st.session_state["final_analysis"], csv_filename, prev_pdf_filename, prev_charts
            )
            st.session_state["final_analysis"] += "\n\n---\n\n" + comp_analysis
            st.session_state["pdf_filename"] = cmpr_pdf_filename
            st.session_state["cmpr_pdf_filename"] = cmpr_pdf_filename
            st.session_state["cmpr_analysis"] = comp_analysis
            st.session_state["all_charts"] = all_charts
            # Update PDF text for chat
            with open(cmpr_pdf_filename, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                pdf_text = ""
                for page in reader.pages:
                    pdf_text += page.extract_text() + "\n"
            st.session_state["pdf_text"] = pdf_text
            st.session_state["comprehensive_done"] = True
            st.success("Comprehensive due diligence completed and PDF updated.")
            with open(cmpr_pdf_filename, "rb") as f:
                st.download_button(
                    label="Comprehensive Due Diligence PDF",
                    data=f,
                    file_name=cmpr_pdf_filename,
                    mime="application/pdf"
                )
    else:
        st.info("Comprehensive due diligence already performed for this report.")
    # Chat
    chat_with_pdf()