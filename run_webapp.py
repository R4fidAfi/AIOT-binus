"""
Launcher script for the Ipomoea Edge-AIoT Backend & Mobile-First Web Application.
Run with: python run_webapp.py
"""

import socket
import uvicorn


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    local_ip = get_local_ip()
    print("=" * 68)
    print("IPOMOEA EDGE-AIoT WEB APPLICATION & FASTAPI SERVER")
    print("=" * 68)
    print(f"Akses Browser Laptop/PC : http://127.0.0.1:8000")
    print(f"Akses Browser HP Petani : http://{local_ip}:8000 (1 jaringan Wi-Fi)")
    print(f"Dokumentasi OpenAPI     : http://127.0.0.1:8000/docs")
    print("=" * 68)
    uvicorn.run("edge_backend.main:app", host="0.0.0.0", port=8000, reload=False)
