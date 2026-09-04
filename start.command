#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "Starting Koshu Standalone OCR & Reading Desk..."
echo

if [ -f "$DIR/koshu-ocr-backend" ]; then
    echo "Starting compiled binary server..."
    "$DIR/koshu-ocr-backend" &
    BACKEND_PID=$!
    sleep 3
    open http://localhost:8000/
    cleanup() {
        echo "Stopping Koshu Standalone OCR server..."
        kill $BACKEND_PID 2>/dev/null
        exit
    }
    trap cleanup SIGINT SIGTERM EXIT
    while kill -0 $BACKEND_PID 2>/dev/null; do
        sleep 1
    done
elif [ -f "$DIR/dist/koshu-ocr-backend/koshu-ocr-backend" ]; then
    echo "Starting compiled binary server..."
    "$DIR/dist/koshu-ocr-backend/koshu-ocr-backend" &
    BACKEND_PID=$!
    sleep 3
    open http://localhost:8000/
    cleanup() {
        echo "Stopping Koshu Standalone OCR server..."
        kill $BACKEND_PID 2>/dev/null
        exit
    }
    trap cleanup SIGINT SIGTERM EXIT
    while kill -0 $BACKEND_PID 2>/dev/null; do
        sleep 1
    done
else
    echo "Compiled binary release not found. Launching via Python launcher..."
    if [ -z "$1" ]; then
        python3 "$DIR/scripts/skill_launcher.py" start
    else
        python3 "$DIR/scripts/skill_launcher.py" "$@"
    fi
fi
