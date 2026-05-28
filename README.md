# Salesforce Invoice Automation Pipeline

Python pipeline that automates end-to-end invoice processing for SMB clients.

## Result
- 70% reduction in processing time
- 200+ monthly records processed automatically
- Zero production errors

## How it works
1. Reads client data from Excel
2. Matches each client with their PDF invoice
3. Uploads and submits records to Salesforce via REST API
4. Dry-run mode validates every match before touching live data

## Stack
Python · openpyxl · pdfplumber · Salesforce REST API · pytest · Git

## Setup
```bash
pip install -r requirements.txt
```
Configure your credentials in `config.py` before running.

## Testing
```bash
pytest tests/
```
