# Vendor Due Diligence Report Generator - Code Analysis

## Overview
This code is a Streamlit application that generates due diligence reports for companies or stocks. The application allows users to input a company name or stock ticker, select a date range, and generate both basic and comprehensive due diligence reports in PDF format.

## Key Components

### Libraries and Dependencies
- **Streamlit**: For the web interface
- **yfinance**: For fetching stock market data
- **FPDF**: For generating PDF reports
- **PyPDF2**: For reading PDF content
- **Azure AI**: Using `AIProjectClient` for AI-based analysis and generating insights
- **dotenv**: For loading environment variables

### Main Features

1. **Ticker Resolution**:
   - Converts company names to stock tickers using Azure AI when needed
   - Uses both direct lookup and Bing search capabilities

2. **Basic Due Diligence Report**:
   - Fetches stock data for the specified ticker and date range
   - Calculates basic metrics (start price, end price, change percentage, volatility)
   - Generates charts of stock performance
   - Creates a PDF report with the analysis

3. **Comprehensive Due Diligence**:
   - Builds on the basic report with more in-depth analysis
   - Uses Azure's AI capabilities to analyze broader market conditions, cashflows, debt, and liquidity
   - Explicitly concludes whether due diligence passes or fails
   - Updates the PDF with comprehensive analysis and additional charts

4. **Chat Interface**:
   - Allows users to ask questions about the generated report
   - Uses the report content as context for answering queries

5. **PDF Generation**:
   - Creates customized PDFs with formatting for headings and content
   - Includes generated charts and tables within the reports
   - Offers download buttons for both basic and comprehensive reports

### Technical Implementation

1. **State Management**:
   - Uses Streamlit's session state to preserve data between interactions
   - Maintains history of reports, analyses, and chart images

2. **AI Integration**:
   - Leverages Azure AI capabilities through:
     - Code Interpreter Tool for data analysis
     - Bing Grounding Tool for market research
     - GPT-4o model for generating insights and answering questions

3. **Data Visualization**:
   - Downloads stock data and saves it to CSV
   - Uses code interpreter to generate charts
   - Embeds charts in both the web interface and PDF reports

4. **Custom PDF Handling**:
   - Custom FPDF class for formatting text (bold headers, etc.)
   - Latin-1 encoding to handle special characters
   - Integration of charts and text in a structured format

## Workflow
1. User enters company name/ticker and date range
2. Application resolves to correct ticker if needed
3. Basic due diligence report is generated with stock data
4. User can choose to generate a comprehensive report for deeper analysis
5. Reports can be downloaded as PDFs
6. User can ask questions about the reports via chat interface

## Security and Configuration
- Uses environment variables for Azure AI credentials
- Loads configuration from .env file
- Properly manages Azure resources (creates and deletes agents/threads)
