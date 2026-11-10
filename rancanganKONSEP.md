# MASTER CONTEXT & SYSTEM SPECIFICATION

## Project Title
Pengembangan Sistem Edge-AIoT Berbasis Dual-Surface 5-Stage Cascaded Deep Learning dan Fusi Mikroklimat untuk Deteksi Indikasi Penyakit, Segmentasi Lesi, serta Rekomendasi Keputusan Budidaya pada Daun Kangkung (*Ipomoea aquatica*)

---

## 1. Tujuan & Latar Belakang Masalah (Hasil Validasi Lapangan Petani)
Proyek ini dikembangkan untuk kompetisi AIoT dan penelitian akademik. Berdasarkan observasi dan wawancara langsung dengan petani kangkung lokal di Indonesia, ditemukan fakta lapangan krusial yang menjadi dasar logika sistem:

1. **Varietas Tanaman:** Terdapat 2 varietas utama, yaitu **Kangkung Daun Lebar** dan **Kangkung Daun Sempit (Paris)**. Sistem menghitung keparahan (*severity*) menggunakan rasio piksel proporsional agar akurat dan invarian terhadap kedua bentuk morfologi daun.
2. **Penyakit Utama ("Brontok/Burik") & Karakteristik Asimetris 2 Sisi Daun:**
   - Penyakit paling merusak adalah **Karat Putih (*White Rust* - *Albugo ipomoeae-aquaticae*)** yang bersifat asimetris: memunculkan bercak kuning pucat (*klorosis*) di **permukaan atas daun (adaksial)** dan **bintil/pustula putih menonjol (*sori sporangia*) di permukaan bawah daun (abaksial)**.
   - Penyakit penting lainnya adalah **Bercak Daun (*Cercospora ipomoeae*)** dan **Hawar Daun (*Rhizoctonia solani*)** yang memunculkan bercak coklat nekrotik tanpa pustula putih di bawah daun.
3. **Pemicu Cuaca Ekstrem ("Habis Hujan Langsung Panas"):** Penyakit meledak dalam $< 24\text{ jam}$ ketika hujan/penyiraman malam hari ($\text{RH} > 80\text{–}85\%$) langsung diikuti sinar matahari terik di siang hari ($\text{Suhu } 28\text{–}32^\circ\text{C}$), menciptakan uap panas-lembap di kanopi.
4. **Masalah Layu Fisiologis vs Penyakit:** Sering terjadi kondisi **akar bawah segar dan tanah bawah basah, tetapi tanah lapisan atas (topsoil 3–5 cm) kering**, menyebabkan tanaman layu di siang hari. Petani sering salah mengira gejala layu/kuning ini sebagai penyakit, sehingga menyemprot pestisida (*Curacron* / *Antracol*) secara berlebihan setiap 2 hari sekali.
5. **Dampak Ekonomi & Panen Dini:** Jika penyakit sudah menyebar parah, petani mengalami **kerugian 50% (langsung dibuang)**. Karena penyakit menyebar sangat cepat dari hari ke hari, pada kangkung yang sudah mendekati masa panen ($\ge 16\text{ HST}$), tindakan terbaik adalah **Panen Dini (*Early Harvest*)** daripada menyemprot pestisida kimia yang meninggalkan residu berbahaya.
6. **Ergonomi Alat & Implementasi Lapangan/Lomba:** Petani merasa ribet jika harus memetik daun satu per satu dan membawanya ke kotak di pinggir lahan. Oleh karena itu, alat dirancang sebagai **In-Situ Overhead & Matte-Black Flip-Stage Rig** di atas petak sampel tanaman untuk memeriksa **permukaan atas dan bawah daun secara non-destruktif (tanpa memetik daun)**.

---

## 2. Arsitektur Hardware & Optimasi Komputasi Edge (Hybrid Edge-AIoT)

### A. Edge AI Server & Inspection Rig: Arduino UNO Q
Arduino UNO Q memiliki arsitektur *dual-processor* dengan pembagian beban kerja yang telah dioptimasi untuk kapasitas RAM 2 GB LPDDR4X dan penyimpanan 16 GB eMMC:

1. **MPU: Qualcomm Dragonwing QRB2210 (Quad-Core Cortex-A53 @ 2.0 GHz - Debian Linux)**
   - Menjalankan **FastAPI Backend Server & Uvicorn** sebagai *single unified server* (melayani REST API, WebSocket/SSE, sekaligus menyajikan **Mobile-First Web Application HTML5/TailwindCSS/JS** tanpa beban tambahan server Streamlit, menghemat ~500 MB RAM).
   - Mengakuisisi **2 citra resolusi tinggi (1080p)** per siklus inspeksi (**Citra 1: Atas Daun / Adaksial** dan **Citra 2: Bawah Daun / Abaksial**) dari **USB Webcam** via OpenCV (`opencv-python-headless`).
   - Menerapkan protokol **LED Warm-up (300–500 ms) + 5-Frame V4L2 Buffer Flush (`cap.grab()`)** sebelum mengambil gambar untuk mencegah *frame lag* atau gambar gelap/silau, serta kompresi `.jpg` (kualitas 85%) dengan *auto-rotation* untuk menjaga ruang eMMC 16 GB.
   - Menjalankan inferensi **5-Stage High-Precision Computer Vision Pipeline** menggunakan **ONNX Runtime** pada resolusi kerja ringan $256 \times 256$ dengan pembatasan thread (`intra_op_num_threads = 2`), menghasilkan waktu inferensi total $< 0,45\text{ detik/citra}$ ($< 0,9\text{ detik}$ untuk 2 sisi daun) dan pemakaian RAM sistem total $< 900\text{ MB}$.
   - Menjalankan **Multimodal Decision Support Engine** (fusi hasil AI 2 sisi daun + gradien mikroklimat + topsoil moisture + umur HST).
   - Menyimpan data telemetri, riwayat inspeksi 2 sisi daun, dan *path* citra ke **SQLite Database**.

2. **MCU: STM32U585 (Menjalankan Arduino Core / Zephyr RTOS)**
   - Berkomunikasi dengan MPU Linux melalui internal IPC/RPC atau Serial Bridge (`115200 bps`).
   - Mengontrol **LED Diffuser Ring 5V** (via PWM/MOSFET di Pin Digital `D3`) agar menyala dengan intensitas terkalibrasi hanya saat kamera mengambil gambar (menjamin konsistensi iluminasi dan menghilangkan bayangan/glare).
   - Membaca **Tombol Fisik Trigger Capture 2-Tahap** (Pin Digital `D2` `INPUT_PULLUP`):
     - Tekanan ke-1: Memicu akuisisi **Citra Atas Daun (Adaksial)**.
     - Tekanan ke-2 (setelah daun dibalik di atas *Flip-Stage*): Memicu akuisisi **Citra Bawah Daun (Abaksial)** dan memulai analisis AI otomatis.
   - Menampilkan indikator status sistem (Siaga, Menunggu Balik Daun, Memproses AI, Selesai/Alert) pada LED onboard/matriks UNO Q.

### B. Wireless Microclimate Field Node: ESP32 DevKit V1
Dipasang langsung pada petak/baki tanaman kangkung dan mengirim data ke UNO Q via Wi-Fi (`HTTP POST JSON` setiap 30–60 detik):

1. **Sensor Suhu & Kelembapan Udara (DHT22):**
   - Pin `VCC` -> `3V3`, `GND` -> `GND`, `DATA` -> `GPIO 4` (dengan *pull-up resistor* 4.7k–10k Ohm).
   - Fungsi: Memantau suhu dan RH kanopi serta mendeteksi anomali gradien transisi **"Hujan-ke-Panas" (*Post-Rain Heat Spike*)**.
2. **Sensor Kelembapan Tanah (Capacitive Soil Moisture Sensor v1.2):**
   - Pin `VCC` -> `3V3`, `GND` -> `GND`, `AOUT` -> `GPIO 34` (`ADC1_CH6` - Input Only, bebas interferensi Wi-Fi ESP32).
   - Penempatan Fisik: Ditancapkan secara dangkal pada **lapisan topsoil (kedalaman 3–5 cm)** untuk memantau zona akar serabut aktif dan mendeteksi kasus *"atas kering, bawah basah"*.
   - Pengolahan Sinyal: Rata-rata bergerak (*moving average*) 10 sampel ADC dan dikalibrasi secara gravimetri (`0%` udara kering, `100%` tanah jenuh air).

### C. Desain Mekanik & Media Implementasi Lomba ("Smart Tray & Flip-Stage Kit")
Untuk kemudahan *pitching* di hadapan dewan juri dan ergonomi di lahan:
1. **Overhead Gantry + Non-Destructive Matte-Black Flip-Stage:**
   - Kamera USB + LED Diffuser Ring dipasang menghadap ke bawah pada jarak fokus tetap ($\pm 20\text{ cm}$).
   - Tepat di bawah kamera setinggi kanopi dipasang **Pelat Sandaran Hitam Doff (*In-Situ Flip-Stage* ukuran $10 \times 10\text{ cm}$ bercelah tangkai)**. Daun diselipkan di atas pelat hitam ini tanpa dipetik dari batangnya untuk difoto bagian atasnya, lalu dibalik untuk difoto bagian bawahnya.
   - Fungsi ganda: Menjaga jarak fokus kamera 100% konsisten (anti-blur) dan mengisolasi daun sampel dari keruwetan daun lain/tanah di bawahnya.
2. **3-in-1 Modular Demo Tray (Baki 3 Skenario Penjurian):**
   - **Petak 1 (Sehat Ideal):** Kangkung segar + tanah lembap ideal (`60–70%`) $\rightarrow$ Demo kondisi `Sehat (0%)`.
   - **Petak 2 (Simulasi "Atas Kering, Bawah Basah"):** Lapisan topsoil 3–5 cm kering (`< 35%`) + daun tampak layu $\rightarrow$ Demo disambiguasi `Stres Air Abiotik (Jangan Semprot Pestisida!)`.
   - **Petak 3 (Infeksi Brontok / Bercak Daun Umur Panen):** Kangkung $\ge 16\text{ HST}$ bergejala klorosis atas & bintil putih bawah $\rightarrow$ Demo deteksi `Karat Putih (Albugo)` & rekomendasi `Panen Dini`.

---

## 3. Pipeline Metode AI 5-Lapis (Target Akurasi ~99%) & Perhitungan Dual-Surface Severity

### A. Strategi Dataset (Hybrid Curated Dataset)
1. **Baseline:** *Gima Kolmi Leaf Dataset* (Mendeley DOI: `10.17632/hp4xjdk2y6.1`, 730 citra asli *Ipomoea aquatica*).
2. **Pengaya:** Subset terkurasi dari Roboflow Universe (gejala *White Blister/Rust* dan bercak daun).
3. **Kalibrasi Lokal Dual-Surface:** 150–200 pasang citra daun kangkung lokal Indonesia (Daun Lebar & Daun Paris, sisi **Atas/Adaksial** dan **Bawah/Abaksial**) yang diambil menggunakan USB Webcam sistem di atas *Flip-Stage*.
4. **Aturan Pencegahan Data Leakage & Semi-Automated Labeling:**
   - Pembagian Train (70%), Validation (15%), dan Test (15%) dilakukan pada pasangan citra asli **sebelum** augmentasi.
   - Pembuatan *ground-truth mask* 3 kelas dibantu metode *Semi-Automated Pseudo-Labeling* berbasis ruang warna CIELAB/HSV dan diverifikasi secara manual.

### B. Arsitektur Pemrosesan Computer Vision 5-Lapis (5-Stage High-Precision Pipeline)
Setiap citra (baik **Citra Atas Daun** maupun **Citra Bawah Daun**) melewati 5 lapis pemrosesan berikut:

1. **Lapis 1 - Normalisasi Iluminasi Ruang Warna CIELAB (`CLAHE`):**
   - Citra kerja ($256 \times 256$) dikonversi dari `RGB` ke `CIELAB` ($L^*, a^*, b^*$).
   - Algoritma **CLAHE (*Contrast Limited Adaptive Histogram Equalization*)** diterapkan khusus pada kanal Luminance ($L^*$) untuk menetralkan variasi cahaya luar dan menajamkan kontras bintil putih *Albugo* serta bercak klorosis/nekrosis (~4 ms di UNO Q).

2. **Lapis 2 - Hybrid Background Suppression (Isolasi ROI Daun):**
   - Menghitung indeks vegetasi **ExG (*Excess Green*: $2G - R - B$)** dikombinasikan dengan segmentasi ruang warna `HSV`, *Otsu Thresholding*, dan *Morphological Flood-Fill / Convex Hull* untuk mempertahankan bagian dalam kontur daun (termasuk bercak sakit di dalam daun) sekaligus mengubah seluruh piksel latar belakang (tanah/baki/batang luar) menjadi hitam murni `(0, 0, 0)` (~5 ms di UNO Q).
   - Memastikan 100% fitur konvolusi jaringan saraf hanya fokus pada permukaan daun tanpa gangguan tekstur tanah.

3. **Lapis 3 - Dual-Check Cross-Verification Cascaded Deep Learning (ONNX):**
   - **Tahap 3A: Gating Classification (MobileNetV2 - Input $224 \times 224$):**
     - Mengklasifikasikan citra menjadi `Healthy` vs `Diseased_Indication` beserta *Confidence Score*.
     - **Logika Soft-Gating & Verifikasi Silang:**
       - Jika `Healthy` dengan **Confidence $\ge 95\%$** DAN lolos cek cepat spektrum pustula putih $\rightarrow$ Hentikan pipeline untuk sisi daun tersebut, tetapkan `Severity Sisi = 0%`.
       - Jika terdeteksi `Diseased_Indication` ATAU Confidence `Healthy` $< 95\%$ (zona ragu/gejala dini) $\rightarrow$ Lanjut ke **Tahap 3B (U-Net)**.
       - Dilengkapi **2-Way Test-Time Augmentation (TTA Horizontal Flip)** khusus jika *confidence* berada di zona perbatasan ($85\%\text{–}94\%$).
   - **Tahap 3B: Multi-Class Semantic Segmentation (MobileNetV2-UNet - Input $256 \times 256$):**
     - Menghasilkan *Pixel Mask* 3 Kelas:
       - Kelas `0` = Background (Latar Belakang)
       - Kelas `1` = Jaringan Daun Sehat (*Healthy Leaf*)
       - Kelas `2` = Area Lesi (*Lesion*: Bintil Putih Brontok / Bercak Coklat Nekrotik / Klorosis)

4. **Lapis 4 - Morphological & Chromaticity Post-Processing (Filter Anti-Noise & Bayangan):**
   - **Speckle Removal (`cv2.connectedComponentsWithStats`):** Menghapus bintik *noise* terisolasi berukuran $< 12\text{ piksel}$ pada Kelas `2`.
   - **Shadow vs. Lesion Disambiguation:** Memvalidasi piksel Kelas `2` terhadap kanal $L^*, a^*, b^*$. Piksel gelap yang disebabkan oleh bayangan daun (nilai $L^*$ rendah namun rasio kehijauan $a^*$ masih normal) dikembalikan menjadi Kelas `1` (*Healthy Leaf*).
   - **Koreksi Silang Akhir:** Jika setelah pemfilteran luas piksel lesi valid $< 0,1\%$ dari total luas daun (misal akibat pantulan tetesan air), status dikoreksi kembali menjadi `Healthy (Severity = 0%)`.

5. **Lapis 5 - Strategi Training Akademik di PC/Colab (Penjamin Akurasi ~99% Tanpa Overfitting):**
   - Dikerjakan pada tahap pelatihan (`/ai_training/`), menggunakan **Combined Multi-Class Focal Loss ($\gamma=2.0$) + Dice Loss** untuk menangani *class imbalance* ekstrem pada bintil kecil *Albugo*.
   - Menerapkan **Hard Negative Mining** (memasukkan sampel daun sehat yang basah berembun dan berbayang ke dalam data latih kelas sehat), **Label Smoothing (`0.05`)**, dan **Cosine Annealing Learning Rate Schedule**.

### C. Rumus Kalkulasi Dual-Surface Severity & Identifikasi Spesifik Patogen
1. **Perhitungan Severity Per Sisi Daun:**
   $$\text{Severity}_{\text{atas}} (\%) = \left( \frac{P_{2,\text{atas}}}{P_{1,\text{atas}} + P_{2,\text{atas}}} \right) \times 100\%, \quad \text{Severity}_{\text{bawah}} (\%) = \left( \frac{P_{2,\text{bawah}}}{P_{1,\text{bawah}} + P_{2,\text{bawah}}} \right) \times 100\%$$
2. **Perhitungan Severity Final (Dual-Surface Fusion):**
   $$\text{Severity}_{\text{final}} (\%) = \max\left( \text{Severity}_{\text{atas}}, \, \text{Severity}_{\text{bawah}} \right)$$
3. **Identifikasi Spesifik Berbasis Asimetri 2 Sisi Daun:**
   - Jika $\text{Severity}_{\text{bawah}} > 0\%$ dengan dominasi spektrum pustula terang ($L^*$ tinggi, $b^*$ rendah/netral) disertai klorosis pada sisi atas $\rightarrow$ **Teridentifikasi Spesifik: Karat Putih / Brontok (*Albugo ipomoeae-aquaticae*)**.
   - Jika lesi dominan pada sisi atas/bawah berupa bercak coklat nekrotik tanpa pustula putih menonjol di bawah daun $\rightarrow$ **Teridentifikasi Spesifik: Bercak/Hawar Daun (*Cercospora* / *Rhizoctonia*)**.
4. **Kategori Keparahan ($\text{Severity}_{\text{final}}$):**
   - `0%` = **Sehat**
   - `0.1% - 5.0%` = **Ringan (Gejala Awal)**
   - `5.1% - 15.0%` = **Sedang**
   - `15.1% - 30.0%` = **Berat**
   - `> 30.0%` = **Sangat Berat**

---

## 4. Logika Fusi Keputusan & Rekomendasi Aksi (Complete Decision Matrix)

### A. Parameter Fase Pertumbuhan (HST - Hari Setelah Tanam)
Sistem menghitung **HST secara otomatis** dari Tanggal Mulai Tanam (atau dapat diatur manual untuk simulasi penjurian):
- **Fase Bibit (1–7 HST):** Akar masih sangat dangkal, butuh kelembapan topsoil tinggi (pola siram 3x sehari).
- **Fase Remaja (8–15 HST):** Pertumbuhan vegetatif cepat, kelembapan sedang (pola siram 2x sehari).
- **Fase Dewasa/Panen ($\ge 16\text{ HST}$):** Pola siram 1x sehari. **Zona Larangan Pestisida Kimia** (*Pre-Harvest Interval*) dan rentan gagal panen 50% jika penyakit menyebar.

### B. Algoritma Deteksi Cuaca "Habis Hujan Langsung Panas" (*Post-Rain Heat Spike*)
Mengevaluasi *sliding window* data telemetri 6 jam terakhir di SQLite:
$$\text{Post-Rain Heat Spike} = \text{TRUE jika: } \left(\max(\text{RH}_{6\text{ jam}}) > 85\%\right) \land \left(T_{\text{saat ini}} \ge 30^\circ\text{C}\right) \land \left(\Delta\text{RH}_{\text{turun}} \ge 15\% \text{ dalam } \le 3\text{ jam}\right)$$

### C. Matriks Aturan Keputusan Lengkap (Decision Engine)
1. **Kondisi 1 - Tanaman Sehat & Lahan Ideal (🟢 AMAN):**
   - **Syarat:** `Severity Final == 0%` + `Soil Moisture Topsoil >= 35%` + `Post-Rain Heat Spike == FALSE`.
   - **Rekomendasi:** *"Tanaman Sehat (Atas & Bawah Daun Bersih). Lanjutkan jadwal penyiraman sesuai fase HST."*
2. **Kondisi 2 - Peringatan Dini Cuaca Pemicu Brontok (🔵 WASPADA CUACA):**
   - **Syarat:** `Severity Final == 0%` + `Post-Rain Heat Spike == TRUE`.
   - **Rekomendasi:** *"WASPADA CUACA PEMICU BRONTOK (Albugo)! Terdeteksi transisi lembap-ekstrem ke panas terik. JANGAN menyiram daun pada sore/malam hari agar spora tidak berkecambah."*
3. **Kondisi 3 - Disambiguasi Stres Air / Layu Fisiologis (🟡 STRES AIR ABIOTIK - JANGAN SEMPROT PESTISIDA):**
   - **Syarat:** `Severity Final == 0%` (tidak ada bintil/bercak patogen pada ke-2 sisi daun) + **`Soil Moisture Topsoil < 35%` (Kering)** + `Suhu > 30°C`.
   - **Rekomendasi:** *"INDIKASI STRES ABIOTIK (Dehidrasi Topsoil 3–5 cm). Daun layu karena zona akar serabut atas kering meskipun tanah bawah basah. DILARANG menyemprot pestisida (*Curacron/Antracol*)! Segera lakukan penyiraman air."*
4. **Kondisi 4 - Infeksi Dini pada Fase Bibit/Remaja (🟠 PENANGANAN DINI TERARAH):**
   - **Syarat:** `Severity Final 0.1% - 5.0%` + `Umur < 16 HST`. *(Jika `Soil Moisture < 35%`, tambahkan instruksi siram akar tanpa membasahi daun).*
   - **Rekomendasi:** *"Gejala awal terdeteksi ([Jenis Patogen: Karat Putih / Bercak Daun]). Pangkas helai daun yang bergejala dan lakukan penyemprotan fungisida terarah/agen hayati hanya pada titik terinfeksi. Kurangi kelembapan kanopi."*
5. **Kondisi 5 - Infeksi Sedang/Berat pada Fase Bibit/Remaja (🔴 ISOLASI / ROGUING DINI):**
   - **Syarat:** `Severity Final > 5.0%` + `Umur < 16 HST`.
   - **Rekomendasi:** *"PERINGATAN PENYEBARAN CEPAT! Keparahan > 5% pada tanaman muda. Segera cabut dan musnahkan rumpun yang terinfeksi parah (Roguing/Eradikasi) agar spora tidak menulari seluruh petak dalam 24 jam!"*
6. **Kondisi 6 - Gejala Ringan pada Fase Siap Panen (🟠 SANITASI PRA-PANEN TANPA KIMIA):**
   - **Syarat:** `Severity Final 0.1% - 5.0%` + `Umur >= 16 HST`.
   - **Rekomendasi:** *"Tanaman sudah memasuki usia panen (>= 16 HST) dengan gejala ringan. DILARANG menyemprot pestisida kimia untuk mencegah residu beracun! Buang daun bergejala dan bersiap lakukan panen jika cuaca memburuk."*
7. **Kondisi 7 - Penyelamatan Ekonomi / Panen Dini (🔴 DARURAT EKONOMI - PANEN DINI SEKARANG):**
   - **Syarat:** `Severity Final > 5.0%` + `Umur >= 16 HST`.
   - **Rekomendasi:** *"PERINGATAN EKONOMI KRITIS! Penyakit ([Karat Putih / Bercak Daun]) berisiko menyebar 2x lipat dalam < 24 jam. JANGAN semprot pestisida! Rekomendasi mutlak: LAKUKAN PANEN DINI SEKARANG untuk menyelamatkan hasil panen (mencegah kerugian 50%) dan menjaga sayur bebas residu kimia!"*

---

## 5. Desain Mobile-First Web Application (Interaktif di HP Petani & Layar Juri)

Web Application disajikan langsung oleh FastAPI (`Jinja2 / Static HTML5 + TailwindCSS + Vanilla JS + Chart.js`) dengan navigasi bawah (*Bottom Navigation Bar*) 4 Menu Utama:

1. **Menu 1: `🔍 Inspeksi` (Beranda & Dual-Surface AI Scanner):**
   - Menampilkan *status bar* ringkas (HST saat ini, Suhu, RH, Topsoil Moisture).
   - **Alur Interaktif 4 Langkah:**
     1. **Capture Sisi 1 (Atas Daun):** Tekan tombol di HP atau tombol fisik UNO Q $\rightarrow$ Foto Atas Daun langsung tampil di Kotak 1.
     2. **Capture Sisi 2 (Bawah Daun):** Muncul instruksi *"Balik Daun"* $\rightarrow$ Tekan tombol lagi $\rightarrow$ Foto Bawah Daun langsung tampil di Kotak 2.
     3. **Animasi Pemrosesan AI (*Dual Laser Scanning*):** Efek sinar pemindai menyapu kedua foto disertai teks tahapan Lapis 1 s/d Lapis 4 dan Fusi Mikroklimat (~1.2 detik).
     4. **Tampilan Hasil & Solusi:** Tombol *toggle* **Foto Asli vs Overlay Mask Penyakit** (untuk Atas & Bawah Daun), rincian `Severity Atas (%)`, `Severity Bawah (%)`, `Severity Final (%)`, **Kartu Keputusan Berwarna**, dan **Daftar Solusi Pencegahan/Penanganan**.
2. **Menu 2: `🌡️ Kondisi Lahan` (Monitor Topsoil & Radar Cuaca Brontok):**
   - Meteran visual kelembapan topsoil 3–5 cm (*Kering <35%*, *Ideal 35–70%*, *Jenuh >70%*).
   - Indikator & grafik 6–24 jam detektor *Post-Rain Heat Spike* ("Habis Hujan Langsung Panas").
   - Panduan jadwal penyiraman harian otomatis sesuai fase HST.
3. **Menu 3: `📋 Riwayat` (Log Pemeriksaan & Grafik Tren Keparahan):**
   - Grafik *Severity Trend* dari waktu ke waktu (bukti visual kecepatan penyebaran penyakit bagi petani & juri).
   - Galeri kartu riwayat inspeksi sebelumnya (lengkap dengan foto Atas/Bawah, mask, dan rekomendasi).
4. **Menu 4: `⚙️ Kebun & Alat` (Profil Tanam Otomatis & Mode Simulasi Juri):**
   - Pengaturan **Tanggal Mulai Tanam** & **Varietas Kangkung** (agar HST dihitung otomatis setiap hari tanpa perlu input berulang).
   - Status kesehatan hardware (ESP32 Online/Offline, Kamera USB, MCU STM32, tombol uji LED Ring).
   - **Panel Mode Simulasi Penjurian (*Judge Demo Override*):** Memungkinkan pengujian cepat berbagai kombinasi umur HST dan kondisi cuaca ekstrem saat presentasi lomba.

---

## 6. Rencana Struktur Direktori Software & Firmware

Proyek dibangun secara modular dengan struktur direktori berikut:
1. `/firmware_esp32/` -> `esp32_field_node.ino`: Kode C++ Arduino IDE untuk ESP32 (Pembacaan DHT22, filter rata-rata 10 sampel ADC Soil Moisture Topsoil + kalibrasi gravimetri, pengiriman HTTP POST JSON ke FastAPI).
2. `/firmware_uno_q_mcu/` -> `stm32_rig_controller.ino`: Kode C++ untuk sisi STM32U585 pada Arduino UNO Q (Kontrol PWM LED Diffuser Ring Pin D3, pembacaan tombol trigger fisik 2-tahap Pin D2 dengan *debounce*, indikator LED matriks, komunikasi Serial/IPC ke Linux MPU).
3. `/ai_training/` -> Pipeline pelatihan PyTorch di PC/Google Colab:
   - `dataset_pipeline.py` (Split 70/15/15 anti-*data leakage*, augmentasi, & *semi-automated pseudo-labeling* CIELAB/HSV).
   - `train_mobilenet_gating.py` (Training Tahap 1 MobileNetV2 + *Hard Negative Mining* + *Label Smoothing*).
   - `train_unet_segmentation.py` (Training Tahap 2 MobileNetV2-UNet $256 \times 256$ dengan *Combined Focal + Dice Loss*).
   - `evaluate_and_export_onnx.py` (Kalkulasi metrik akademik: Accuracy, Macro-F1, Pixel Accuracy, mIoU, Dice Score, MAE, RMSE, $R^2$, serta ekspor ke `.onnx`).
4. `/edge_backend/` -> Layanan Python terpadu di Debian Linux UNO Q:
   - `main.py` (FastAPI server: *hosting* Web App, endpoints `/api/v1/telemetry`, `/api/v1/capture/{side}`, `/api/v1/analyze-dual`, `/api/v1/history`, `/api/v1/settings`, dan `/api/v1/demo-simulate`).
   - `camera_service.py` (OpenCV USB Webcam 1080p capture + protokol sinkronisasi LED Ring via STM32 + *5-frame buffer flush* + auto-cleanup).
   - `ai_inference.py` (Implementasi **5-Stage High-Precision Vision Pipeline**: CIELAB CLAHE $\rightarrow$ ExG/HSV Background Suppression $\rightarrow$ ONNX Runtime Dual-Check MobileNetV2 & U-Net $256 \times 256$ $\rightarrow$ Morphological & Shadow Filter $\rightarrow$ Kalkulasi *Dual-Surface Severity* & Overlay Mask).
   - `decision_engine.py` (Algoritma gradien *Post-Rain Heat Spike*, disambiguasi stres air topsoil, dan 7 aturan matriks keputusan HST).
   - `database.py` (Skema tabel SQLite3 untuk telemetri, riwayat inspeksi 2 sisi daun, dan konfigurasi profil kebun).
5. `/web_app/` -> Frontend Mobile-First Web Application (di-mount langsung oleh FastAPI):
   - `index.html` (Antarmuka 4 Menu dengan TailwindCSS & ikon interaktif).
   - `style.css` (Animasi *dual laser scanning*, *step progress*, transisi kartu warna, dan *responsive mobile layout*).
   - `app.js` (Logika *fetch API*, kontrol alur *Capture Atas $\rightarrow$ Capture Bawah $\rightarrow$ Animasi Scanning $\rightarrow$ Hasil & Toggle Mask*, grafik Chart.js, dan mode simulasi penjurian).
