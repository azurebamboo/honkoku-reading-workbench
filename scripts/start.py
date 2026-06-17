import subprocess
import sys
import os
import time
import webbrowser
import platform
import signal

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    print("Starting Standalone OCR & Reading Desk...")
    
    is_windows = platform.system() == "Windows"
    
    # Locate uvicorn dynamically
    if is_windows:
        local_venv_uvicorn = os.path.join(root_dir, "backend", ".venv", "Scripts", "uvicorn.exe")
        root_venv_uvicorn = os.path.join(root_dir, ".venv", "Scripts", "uvicorn.exe")
        parent_venv_uvicorn = os.path.join(root_dir, "..", "koshu-research-workbench", ".venv", "Scripts", "uvicorn.exe")
        npm_cmd = "npm.cmd"
    else:
        local_venv_uvicorn = os.path.join(root_dir, "backend", ".venv", "bin", "uvicorn")
        root_venv_uvicorn = os.path.join(root_dir, ".venv", "bin", "uvicorn")
        parent_venv_uvicorn = os.path.join(root_dir, "..", "koshu-research-workbench", ".venv", "bin", "uvicorn")
        npm_cmd = "npm"

    if os.path.exists(local_venv_uvicorn):
        uvicorn_path = local_venv_uvicorn
    elif os.path.exists(root_venv_uvicorn):
        uvicorn_path = root_venv_uvicorn
    elif os.path.exists(parent_venv_uvicorn):
        print(f"Using parent workbench virtual environment at: {parent_venv_uvicorn}")
        uvicorn_path = parent_venv_uvicorn
    else:
        # Fallback to system PATH uvicorn
        print("Warning: No virtual environment found. Falling back to system global 'uvicorn'.")
        print("This might fail if global python package dependencies are mismatched.")
        uvicorn_path = "uvicorn"

    # We use CREATE_NEW_PROCESS_GROUP on Windows to allow sending CTRL_BREAK_EVENT
    # This ensures that child processes (like node.exe spawned by npm) are properly killed.
    kwargs = {}
    if is_windows:
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP

    print("Starting Backend...")
    backend_cmd = [
        uvicorn_path,
        "backend.app.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--log-level", "warning"
    ]
    try:
        backend_process = subprocess.Popen(backend_cmd, cwd=root_dir, **kwargs)
    except FileNotFoundError:
        print("Error: Could not run uvicorn. Ensure it is installed globally or python virtual environment is initialized.")
        sys.exit(1)
    
    print("Starting Frontend...")
    frontend_dir = os.path.join(root_dir, "frontend")
    frontend_cmd = [
        npm_cmd,
        "run", "dev",
        "--", "--host", "127.0.0.1", "--port", "5173"
    ]
    try:
        frontend_process = subprocess.Popen(frontend_cmd, cwd=frontend_dir, **kwargs)
    except FileNotFoundError:
        print(f"Error: Could not run npm dev server using '{npm_cmd}'. Ensure Node.js is installed.")
        backend_process.terminate()
        sys.exit(1)
    
    print("Waiting for servers to initialize...")
    time.sleep(3)
    
    print("Opening browser at http://127.0.0.1:5173/ ...")
    if is_windows:
        os.system("start http://127.0.0.1:5173/")
    else:
        webbrowser.open("http://127.0.0.1:5173/")
        
    print("\nWorkbench is running. Press Ctrl+C to stop both servers.")
    
    try:
        while True:
            time.sleep(1)
            if backend_process.poll() is not None or frontend_process.poll() is not None:
                print("A server process exited unexpectedly.")
                break
    except KeyboardInterrupt:
        print("\nShutting down servers...")
    finally:
        def kill_proc(proc, name):
            if proc.poll() is None:
                if is_windows:
                    os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
                proc.wait()
                print(f"{name} stopped.")

        kill_proc(backend_process, "Backend")
        kill_proc(frontend_process, "Frontend")

if __name__ == "__main__":
    main()
