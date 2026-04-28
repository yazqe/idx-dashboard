#!/bin/bash
cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
  echo "Python3 tidak ditemukan"; exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Membuat virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

echo "==============================================="
echo "  IDX Dashboard — http://localhost:5050"
echo "  Jadwal: 09:17 | 12:03 | 15:37 WIB (Sen-Jum)"
echo "  Ctrl+C untuk berhenti"
echo "==============================================="
python3 app.py
