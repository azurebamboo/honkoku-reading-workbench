#!/bin/bash
# Get the directory of the script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "Starting Koshu Standalone OCR & Reading Desk..."
echo "This terminal window must stay open to run the local OCR server."
echo "Closing this window will stop the server."
echo

# Run the backend in the background
./dist/koshu-ocr-backend/koshu-ocr-backend &
BACKEND_PID=$!

# Wait 3 seconds for uvicorn to bind to port 8000
sleep 3

# Open default browser
open http://localhost:8000/

# Trap exit to kill the background server
cleanup() {
    echo "Stopping Koshu Standalone OCR server..."
    kill $BACKEND_PID 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM EXIT

# Keep the shell running so trap works
while kill -0 $BACKEND_PID 2>/dev/null; do
    sleep 1
done
