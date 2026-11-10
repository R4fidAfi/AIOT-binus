"""
Skrip Sederhana untuk Uji Coba Webcam Laptop / Webcam USB Rexus SW-10.
Jalankan dengan perintah:
    python uji_webcam.py
"""

import sys
import time
import cv2


def test_webcam(camera_index: int = 0):
    print("=" * 60)
    print(f"Membuka Webcam (Index: {camera_index})...")
    print("=" * 60)

    # Coba DirectShow dulu (standar Windows), jika gagal coba default
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print(f"[GAGAL] Webcam pada Index {camera_index} tidak dapat dibuka.")
        print("Saran perbaikan:")
        print("1. Pastikan webcam tidak sedang digunakan oleh aplikasi lain (Zoom, Teams, Kamera Windows).")
        print("2. Jika menggunakan webcam eksternal (Rexus), coba jalankan: python uji_webcam.py 1")
        print("3. Pastikan izin kamera aktif di Windows Settings -> Privacy -> Camera.")
        return False

    # Atur resolusi pengujian ke 640x480 (sama persis dengan settingan Arduino UNO Q)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[BERHASIL] Webcam Aktif!")
    print(f"Resolusi Kamera: {actual_w} x {actual_h}")
    print("-" * 60)
    print("KONTROL JENDELA:")
    print("  - Tekan tombol [SPASI] : Ambil dan simpan foto uji (uji_tangkapan.jpg)")
    print("  - Tekan tombol [Q]     : Keluar dari pengujian")
    print("=" * 60)

    prev_time = time.time()
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            print("[PERINGATAN] Gagal membaca frame dari webcam.")
            break

        # Hitung FPS real-time
        now = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(1e-5, now - prev_time))
        prev_time = now

        # Tampilkan teks informasi pada gambar
        hud_text = f"Webcam Index {camera_index} | {actual_w}x{actual_h} | {fps:.1f} FPS"
        cv2.putText(
            frame,
            hud_text,
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 120),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "SPASI: Ambil Foto | Q: Keluar",
            (15, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        cv2.imshow("Uji Coba Webcam Laptop / Rexus SW-10", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:  # Q atau ESC
            print("Pengujian dihentikan oleh pengguna.")
            break
        elif key == 32:  # SPASI
            output_name = f"uji_tangkapan_index{camera_index}.jpg"
            cv2.imwrite(output_name, frame)
            print(f"[FOTO TERSIMPAN] Berhasil mengambil dan menyimpan foto ke: {output_name}")

    cap.release()
    cv2.destroyAllWindows()
    return True


if __name__ == "__main__":
    idx = 0
    if len(sys.argv) > 1:
        try:
            idx = int(sys.argv[1])
        except ValueError:
            idx = 0
    test_webcam(idx)
