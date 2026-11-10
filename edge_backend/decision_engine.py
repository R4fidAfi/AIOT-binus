"""
Multimodal Decision Support Engine for Edge-AIoT Kangkung System.
Uses clear, familiar terminology ("Umur ... Hari") instead of technical abbreviations.
"""

from typing import Any, Dict, List


def get_hst_phase_info(hst: int) -> Dict[str, Any]:
    """Return growth phase details and recommended watering schedule based on plant age in days."""
    hst = max(1, int(hst))
    if hst <= 7:
        return {
            "hst": hst,
            "phase_name": "Fase Bibit (Umur 1–7 Hari)",
            "phase_short": "Fase Bibit",
            "watering_freq": "3x Sehari (Pagi 07.00, Siang 11.30, Sore 15.30)",
            "target_soil_moisture": "60% – 75% (Butuh Tanah Lembab Tinggi)",
            "chemical_restriction": False,
            "note": "Akar masih sangat dangkal (1–3 cm). Jaga tanah lapisan atas agar tidak kering.",
        }
    elif hst <= 15:
        return {
            "hst": hst,
            "phase_name": "Fase Remaja (Umur 8–15 Hari)",
            "phase_short": "Fase Remaja",
            "watering_freq": "2x Sehari (Pagi 07.30 & Sore 15.30)",
            "target_soil_moisture": "50% – 70% (Kelembapan Sedang)",
            "chemical_restriction": False,
            "note": "Daun mulai rimbun. Hindari menyiram daun di atas jam 17.00 agar tidak memicu jamur.",
        }
    else:
        return {
            "hst": hst,
            "phase_name": "Fase Siap Panen (Umur ≥ 16 Hari)",
            "phase_short": "Siap Panen",
            "watering_freq": "1x Sehari (Pagi 08.00 pada area akar)",
            "target_soil_moisture": "45% – 65% (Jaga Daun Tetap Kering)",
            "chemical_restriction": True,
            "note": "Batas aman masa panen: Dilarang menyemprot pestisida kimia. Jika muncul penyakit >5%, segera Panen Dini.",
        }


def detect_post_rain_heat_spike(
    current_temp: float,
    current_rh: float,
    recent_window: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Detect 'Habis Hujan Langsung Panas' (Post-Rain Heat Spike) using 6-hour rolling window.
    """
    if not recent_window:
        max_rh_6h = current_rh
        min_temp_6h = current_temp
    else:
        max_rh_6h = max([float(r.get("humidity", current_rh)) for r in recent_window] + [current_rh])
        min_temp_6h = min([float(r.get("temperature", current_temp)) for r in recent_window] + [current_temp])

    rh_drop = round(max_rh_6h - current_rh, 1)
    temp_rise = round(current_temp - min_temp_6h, 1)

    is_spike = (max_rh_6h > 85.0) and (current_temp >= 30.0) and (rh_drop >= 15.0)

    if is_spike:
        summary = (
            f"Terdeteksi cuaca 'Habis Hujan/Lembab Langsung Panas'! Kelembapan udara sempat mencapai {max_rh_6h:.0f}% "
            f"lalu disusul suhu panas {current_temp:.1f}°C. Kondisi ini memicu jamur Karat Putih (Brontok) dalam <24 jam."
        )
    elif max_rh_6h > 85.0 and current_temp >= 28.5:
        summary = (
            f"Udara sempat sangat lembab ({max_rh_6h:.0f}%) dengan suhu {current_temp:.1f}°C. "
            "Jaga sirkulasi udara dan hindari menyiram tanaman di malam hari."
        )
    else:
        summary = (
            f"Cuaca kebun stabil (Suhu saat ini {current_temp:.1f}°C). "
            "Risiko pemicu jamur dari faktor cuaca rendah."
        )

    return {
        "is_spike": is_spike,
        "max_rh_6h": round(max_rh_6h, 1),
        "rh_drop": rh_drop,
        "temp_rise": temp_rise,
        "summary": summary,
    }


def categorize_severity(severity_pct: float) -> str:
    if severity_pct <= 0.0:
        return "Sehat (0%)"
    elif severity_pct <= 5.0:
        return "Gejala Ringan (0.1% – 5.0%)"
    elif severity_pct <= 15.0:
        return "Kerusakan Sedang (5.1% – 15.0%)"
    elif severity_pct <= 30.0:
        return "Kerusakan Berat (15.1% – 30.0%)"
    else:
        return "Kerusakan Sangat Berat (> 30.0%)"


def evaluate_multimodal_decision(
    severity_top: float,
    severity_bottom: float,
    severity_final: float,
    pathogen_detected: str,
    hst: int,
    variety: str,
    temperature: float,
    humidity: float,
    soil_moisture: float,
    post_rain_heat_spike: bool,
) -> Dict[str, Any]:
    """
    Execute the 7-Condition Multimodal Decision Matrix combining:
    - Dual-Surface AI Severity (Top + Bottom)
    - Lembab Tanah (3-5 cm depth)
    - Canopy Microclimate & Post-Rain Heat Spike
    - Plant Age in Days (Umur Hari)
    """
    hst = max(1, int(hst))
    phase_info = get_hst_phase_info(hst)
    sev_cat = categorize_severity(severity_final)
    topsoil_dry = soil_moisture < 35.0

    # CASE A: No pathogen lesions detected on either leaf surface (Severity == 0%)
    if severity_final <= 0.0:
        # Condition 3: Disambiguasi Stres Air / Layu Kurang Air (Lembab Tanah < 35%)
        if topsoil_dry:
            return {
                "decision_code": "KURANG AIR",
                "decision_title": "LAYU KARENA TANAH KERING — BUKAN PENYAKIT!",
                "decision_level": "WARNING_WATER",
                "severity_category": sev_cat,
                "recommendation": (
                    "Bagian atas dan bawah daun bersih dari bintil maupun bercak penyakit (Kerusakan 0%), "
                    f"tetapi Lembab Tanah sangat kering ({soil_moisture:.0f}%). Tanaman layu karena akar bagian atas "
                    "kekurangan air. JANGAN SEMPROT PESTISIDA! Segera siram dengan air bersih."
                ),
                "action_steps": [
                    "Jangan menyemprotkan pestisida kimia (seperti Curacron/Antracol) karena tanaman tidak sakit.",
                    f"Segera siram air hingga Lembab Tanah kembali ideal ({phase_info['target_soil_moisture']}).",
                    "Jika matahari sedang terik (>31°C), siram perlahan di area akar/tanah.",
                    f"Ikuti jadwal siram {phase_info['phase_short']} (Umur {hst} Hari): {phase_info['watering_freq']}.",
                ],
                "economic_impact": "Hemat biaya pestisida 100% (Mencegah salah semprot obat kimia).",
            }

        # Condition 2: Peringatan Dini Cuaca Pemicu Brontok (Post-Rain Heat Spike)
        if post_rain_heat_spike:
            return {
                "decision_code": "WASPADA CUACA",
                "decision_title": "DAUN MASIH SEHAT, NAMUN CUACA RAWAN PENYAKIT BRONTOK",
                "decision_level": "INFO_WEATHER",
                "severity_category": sev_cat,
                "recommendation": (
                    "Saat ini daun masih sehat (Kerusakan 0%), tetapi sensor mendeteksi cuaca "
                    f"'Habis Hujan/Lembab Langsung Panas' (Suhu {temperature:.1f}°C). "
                    "Kondisi uap lembab-panas ini dapat memicu munculnya bintil putih Brontok dalam <24 jam."
                ),
                "action_steps": [
                    "Jangan menyiram daun pada sore atau malam hari (di atas pukul 16.30) agar daun tidak basah semalaman.",
                    "Pastikan aliran udara di sekitar petak kangkung lancar.",
                    "Periksa kembali bagian bawah daun besok pagi untuk memantau ada tidaknya bintil putih.",
                    "Belum perlu menyemprotkan obat/fungisida karena daun masih sehat.",
                ],
                "economic_impact": "Pencegahan dini sebelum jamur menyerang tanaman.",
            }

        # Condition 1: Kondisi Aman (Healthy + Normal Microclimate)
        return {
            "decision_code": "SEHAT",
            "decision_title": "TANAMAN SEHAT & KONDISI KEBUN IDEAL",
            "decision_level": "SAFE",
            "severity_category": sev_cat,
            "recommendation": (
                f"Tanaman {variety} (Umur {hst} Hari) dalam kondisi sehat. "
                f"Permukaan atas dan bawah daun bersih dari penyakit (0%), serta Lembab Tanah cukup ({soil_moisture:.0f}%)."
            ),
            "action_steps": [
                f"Lanjutkan penyiraman rutin untuk {phase_info['phase_name']}: {phase_info['watering_freq']}.",
                f"Pertahankan Lembab Tanah pada kisaran {phase_info['target_soil_moisture']}.",
                "Tidak diperlukan penyemprotan obat maupun pestisida.",
            ],
            "economic_impact": "Pertumbuhan optimal dan bebas biaya pestisida.",
        }

    # CASE B: Pathogen lesions detected (Severity > 0%)
    water_note = (
        f"Catatan Air: Lembab Tanah juga terdeteksi kering ({soil_moisture:.0f}%). Siram area akar tanpa membasahi daun."
        if topsoil_dry
        else f"Kondisi Air: Lembab Tanah saat ini cukup ({soil_moisture:.0f}%)."
    )

    # Young / Vegetative Plants (Umur < 16 Hari)
    if hst < 16:
        if severity_final <= 5.0:
            # Condition 4: Infeksi Dini pada Tanaman Muda (0.1% - 5.0%, Umur < 16 Hari)
            return {
                "decision_code": "GEJALA AWAL",
                "decision_title": f"GEJALA AWAL TERDETEKSI ({pathogen_detected}) — RAWAT TERARAH",
                "decision_level": "WARNING_EARLY",
                "severity_category": sev_cat,
                "recommendation": (
                    f"Terdeteksi gejala awal {pathogen_detected} dengan tingkat kerusakan ringan "
                    f"(Atas: {severity_top:.1f}%, Bawah: {severity_bottom:.1f}%, Total: {severity_final:.1f}%) "
                    f"pada tanaman Umur {hst} Hari. Segera pangkas daun yang sakit agar tidak menular."
                ),
                "action_steps": [
                    "Petik dan buang jauh dari kebun helai daun yang mulai berbintil putih atau bercak coklat.",
                    "Semprotkan fungisida/agen hayati secara terarah hanya pada area tanaman yang bergejala (terutama bagian bawah daun).",
                    "Hindari menyiram dari atas daun pada sore/malam hari agar penyakit tidak menyebar.",
                    water_note,
                ],
                "economic_impact": "Penanganan cepat menyelamatkan >95% tanaman lainnya.",
            }
        else:
            # Condition 5: Infeksi Sedang/Berat pada Tanaman Muda (> 5.0%, Umur < 16 Hari)
            return {
                "decision_code": "ISOLASI TANAMAN",
                "decision_title": f"PENYAKIT MENYEBAR ({pathogen_detected}) — CABUT RUMPUN SAKIT!",
                "decision_level": "DANGER_ROGUING",
                "severity_category": sev_cat,
                "recommendation": (
                    f"Kerusakan daun telah mencapai {severity_final:.1f}% pada tanaman yang masih muda (Umur {hst} Hari). "
                    "Segera cabut tanaman yang sakit parah agar spora tidak menulari seluruh petak dalam 24 jam!"
                ),
                "action_steps": [
                    "Segera cabut tanaman/rumpun yang berbintil parah dan musnahkan di luar area kebun.",
                    "Berikan perawatan pelindung pada tanaman sehat di sekelilingnya agar penularan terputus.",
                    "Kurangi kelembapan berlebih dan pastikan air tidak menggenang.",
                    water_note,
                ],
                "economic_impact": "Mencegah penularan total ke seluruh bedeng.",
            }

    # Mature / Ready-to-Harvest Plants (Umur >= 16 Hari)
    else:
        if severity_final <= 5.0:
            # Condition 6: Gejala Ringan di Usia Siap Panen (0.1% - 5.0%, Umur >= 16 Hari)
            return {
                "decision_code": "SIAP PANEN",
                "decision_title": "GEJALA RINGAN DI USIA PANEN — JANGAN SEMPROT KIMIA!",
                "decision_level": "WARNING_EARLY",
                "severity_category": sev_cat,
                "recommendation": (
                    f"Tanaman sudah berumur {hst} Hari (Usia Panen) dengan gejala ringan {pathogen_detected} "
                    f"({severity_final:.1f}%). DILARANG menyemprot pestisida kimia karena sayur sudah dekat waktu panen!"
                ),
                "action_steps": [
                    f"Jangan menyemprot pestisida kimia karena tanaman sudah berumur {hst} Hari (mencegah residu racun pada sayur).",
                    "Buang helai daun yang memiliki bercak/bintil ringan.",
                    "Jika cuaca lembab atau habis hujan langsung panas, segera majukan jadwal panen besok pagi.",
                    water_note,
                ],
                "economic_impact": "Sayur tetap aman dikonsumsi dan nilai jual terjaga.",
            }
        else:
            # Condition 7: Penyelamatan Ekonomi / Panen Dini (> 5.0%, Umur >= 16 Hari)
            return {
                "decision_code": "PANEN DINI",
                "decision_title": "PERINGATAN EKONOMI: LAKUKAN PANEN DINI SEKARANG!",
                "decision_level": "DANGER_HARVEST",
                "severity_category": sev_cat,
                "recommendation": (
                    f"Terdeteksi {pathogen_detected} dengan kerusakan {severity_final:.1f}% "
                    f"(Atas: {severity_top:.1f}%, Bawah: {severity_bottom:.1f}%) pada kangkung Umur {hst} Hari (Usia Panen). "
                    "Penyakit dapat menyebar 2x lipat dalam <24 jam! Rekomendasi terbaik: PANEN DINI SEKARANG "
                    "agar tidak rugi gagal panen 50% dan sayur tetap bebas racun pestisida!"
                ),
                "action_steps": [
                    f"Segera lakukan PANEN DINI hari ini pada petak kangkung (Umur {hst} Hari) sebelum penyakit merusak daun sehat lainnya.",
                    "Jangan menyemprotkan pestisida kimia — menyemprot di usia panen hanya membuang biaya dan meninggalkan residu berbahaya.",
                    "Saat mengikat hasil panen, pisahkan helai daun yang berbintil putih agar kualitas ikatan tetap bagus.",
                    "Setelah dipanen, jemur/bersihkan lahan sebelum menanam kloter berikutnya.",
                ],
                "economic_impact": "Menyelamatkan hasil panen (Mencegah kerugian 50% dibuang) & hemat biaya pestisida.",
            }
