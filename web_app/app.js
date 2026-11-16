/**
 * Frontend Controller for Ipomoea Edge-AIoT Web Application
 * Alur Terstruktur:
 * 1. Patokan Data Tanam di Halaman Awal (Jenis Kangkung & Umur Hari)
 * 2. Kamera 1 Frame -> Foto Atas -> Validasi -> Foto Bawah -> Validasi -> Otomatis Proses
 * 3. Tampil 2 Foto Hasil & Keputusan Budidaya
 */

let APP_STATE = {
  activeTab: 'tab-inspect',
  capturePhase: 'TOP_STANDBY', // 'TOP_STANDBY' | 'TOP_LIVE' | 'TOP_VALIDATE' | 'BOTTOM_STANDBY' | 'BOTTOM_LIVE' | 'BOTTOM_VALIDATE' | 'PROCESSING' | 'DONE'
  farm: {},
  hstInfo: {},
  telemetry: {},
  weatherRadar: {},
  latestAnalysis: null,
  topUrls: { orig: null, mask: null, stage: null },
  bottomUrls: { orig: null, mask: null, stage: null },
  telemetryChartInstance: null,
  severityChartInstance: null,
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function showToast(msg, duration = 3200) {
  const banner = document.getElementById('toastBanner');
  const txt = document.getElementById('toastText');
  if (!banner || !txt) return;
  txt.textContent = msg;
  banner.classList.remove('hidden');
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => {
    banner.classList.add('hidden');
  }, duration);
}

function hideToast() {
  const banner = document.getElementById('toastBanner');
  if (banner) banner.classList.add('hidden');
}

/* ================= REAL-TIME CLOCK: KOTA TANGERANG (WIB / UTC+7) ================= */
function updateTangerangLiveClock() {
  const now = new Date();
  const dateEl = document.getElementById('liveClockDate');
  const timeEl = document.getElementById('liveClockTime');
  if (!dateEl && !timeEl) return;

  try {
    const dateOptions = {
      timeZone: 'Asia/Jakarta',
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    };
    const timeOptions = {
      timeZone: 'Asia/Jakarta',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    };

    const dateStr = new Intl.DateTimeFormat('id-ID', dateOptions).format(now);
    let timeStr = new Intl.DateTimeFormat('id-ID', timeOptions).format(now);
    timeStr = timeStr.replace(/\./g, ':');

    if (dateEl) dateEl.textContent = dateStr;
    if (timeEl) timeEl.textContent = timeStr;
  } catch (err) {
    // Robust fallback: kalkulasi manual UTC+7
    const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
    const wib = new Date(utc + (3600000 * 7));
    const days = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
    const months = [
      '', 'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
      'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
    ];
    const pad = (n) => (n < 10 ? '0' : '') + n;
    if (dateEl) dateEl.textContent = `${days[wib.getDay()]}, ${wib.getDate()} ${months[wib.getMonth() + 1]} ${wib.getFullYear()}`;
    if (timeEl) timeEl.textContent = `${pad(wib.getHours())}:${pad(wib.getMinutes())}:${pad(wib.getSeconds())}`;
  }
}

function formatWibTimestamp(tsStr) {
  if (!tsStr) return '-';
  try {
    const clean = String(tsStr).trim().replace('T', ' ').split('.')[0];
    const parts = clean.split(' ');
    if (parts.length >= 2) {
      const dateParts = parts[0].split('-');
      const timePart = parts[1];
      if (dateParts.length === 3) {
        const year = dateParts[0];
        const monthIdx = parseInt(dateParts[1], 10);
        const day = dateParts[2];
        const months = [
          '', 'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
          'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
        ];
        const monthName = months[monthIdx] || dateParts[1];
        return `${day} ${monthName} ${year}, ${timePart} WIB`;
      }
    }
    return `${clean} WIB`;
  } catch (err) {
    return `${tsStr} WIB`;
  }
}

function formatWibTimeOnly(tsStr) {
  if (!tsStr) return '--:--:--';
  const clean = String(tsStr).trim().replace('T', ' ').split('.')[0];
  const parts = clean.split(' ');
  return parts.length >= 2 ? parts[1] : clean.slice(-8);
}

/* ================= NAVIGATION TABS ================= */
function switchTab(tabId) {
  // Jika user pindah menu saat kamera live menyala, matikan kamera otomatis agar UNO Q hemat RAM/CPU
  if (tabId !== 'tab-inspect' && (APP_STATE.capturePhase === 'TOP_LIVE' || APP_STATE.capturePhase === 'BOTTOM_LIVE')) {
    stopLiveWebcamToStandby(true);
  }

  APP_STATE.activeTab = tabId;
  document.querySelectorAll('.tab-panel').forEach((el) => el.classList.add('hidden'));
  const target = document.getElementById(tabId);
  if (target) target.classList.remove('hidden');

  document.querySelectorAll('.bottom-nav-item').forEach((btn) => btn.classList.remove('active'));
  const activeBtn = document.getElementById(`nav-${tabId}`);
  if (activeBtn) activeBtn.classList.add('active');

  if (tabId === 'tab-land') {
    loadTelemetryAndChart();
  } else if (tabId === 'tab-history') {
    loadInspectionHistory();
  }
}

/* ================= PLANT SETUP FORM AT TOP OF INSPECT ================= */
function togglePlantSetupForm(forceState) {
  const box = document.getElementById('plantSetupFormBox');
  const btn = document.getElementById('btnTogglePlantSetup');
  if (!box) return;
  const isHidden = box.classList.contains('hidden');
  const nextShow = typeof forceState === 'boolean' ? forceState : isHidden;

  if (nextShow) {
    box.classList.remove('hidden');
    if (btn) btn.textContent = 'Tutup Pengaturan';
  } else {
    box.classList.add('hidden');
    if (btn) btn.textContent = 'Ubah Data Tanam';
  }
}

function openPlantSetupForm() {
  switchTab('tab-inspect');
  togglePlantSetupForm(true);
}

function toggleHardwareModal(show) {
  const modal = document.getElementById('hardwareModal');
  if (!modal) return;
  if (show) {
    modal.classList.remove('hidden');
  } else {
    modal.classList.add('hidden');
  }
}

/* ================= STATUS & HEADER SYNC ================= */
async function loadStatusAndHeader() {
  try {
    const res = await fetch('/api/v1/status');
    const data = await res.json();
    APP_STATE.farm = data.farm || {};
    APP_STATE.hstInfo = data.hst_info || {};
    APP_STATE.telemetry = data.telemetry || {};
    APP_STATE.weatherRadar = data.weather_radar || {};

    renderHeaderAndSettings(data);
  } catch (err) {
    console.error('Failed to fetch status:', err);
  }
}

function renderHeaderAndSettings(data) {
  const farm = data.farm || {};
  const hstInfo = data.hst_info || {};
  const tel = data.telemetry || {};
  const radar = data.weather_radar || {};

  const ageDays = hstInfo.hst || 16;
  const phaseShort = hstInfo.phase_short || 'Siap Panen';

  document.getElementById('headerPlotInfo').textContent =
    `${farm.plot_name || 'Petak Sampel'} • ${farm.variety || 'Kangkung Daun Lebar'}`;
  document.getElementById('headerHstBadge').textContent = `Umur ${ageDays} Hari`;
  document.getElementById('headerPhaseBadge').textContent = phaseShort;

  // Update Patokan Data Tanam Summary Card on Inspect Page
  const sumVar = document.getElementById('summaryVarietyText');
  const sumAge = document.getElementById('summaryAgeText');
  const sumPlot = document.getElementById('summaryPlotText');
  if (sumVar) sumVar.textContent = farm.variety || 'Kangkung Daun Lebar';
  if (sumAge) sumAge.textContent = `Umur ${ageDays} Hari (${phaseShort})`;
  if (sumPlot) sumPlot.textContent = `Lokasi: ${farm.plot_name || 'Petak Sampel Utama'} • Mulai Tanam: ${farm.planting_date || '-'}`;

  const tempNum = Number(tel.temperature || 28.8);
  const rhNum = Number(tel.humidity || 73.0);
  const soilNum = Number(tel.soil_moisture || 62.0);

  const sensorTimeEl = document.getElementById('barSensorTime');
  if (sensorTimeEl) {
    const rawTime = (tel.timestamp || data.server_time || '');
    sensorTimeEl.textContent = rawTime ? `Update Sensor: ${formatWibTimeOnly(rawTime)} WIB` : 'Live • ESP32';
  }

  // 1. Suhu Udara
  document.getElementById('barTemp').textContent = `${tempNum.toFixed(1)} °C`;
  const barTempSub = document.getElementById('barTempSub');
  const barTempBox = document.getElementById('barTempBox');
  if (tempNum > 31.0) {
    if (barTempSub) {
      barTempSub.textContent = 'Panas Terik';
      barTempSub.className = 'text-[9px] text-amber-300 font-semibold truncate';
    }
    if (barTempBox) barTempBox.className = 'realtime-tile realtime-tile-warn px-2 py-1.5';
  } else {
    if (barTempSub) {
      barTempSub.textContent = 'Normal';
      barTempSub.className = 'text-[9px] text-emerald-400 font-medium truncate';
    }
    if (barTempBox) barTempBox.className = 'realtime-tile px-2 py-1.5';
  }

  // 2. Lembab Udara
  document.getElementById('barHumidity').textContent = `${rhNum.toFixed(0)} %`;
  const barHumiditySub = document.getElementById('barHumiditySub');
  const barHumidityBox = document.getElementById('barHumidityBox');
  if (rhNum >= 85.0) {
    if (barHumiditySub) {
      barHumiditySub.textContent = 'Sangat Lembab';
      barHumiditySub.className = 'text-[9px] text-sky-300 font-semibold truncate';
    }
    if (barHumidityBox) barHumidityBox.className = 'realtime-tile realtime-tile-alert px-2 py-1.5';
  } else {
    if (barHumiditySub) {
      barHumiditySub.textContent = 'Ideal';
      barHumiditySub.className = 'text-[9px] text-emerald-400 font-medium truncate';
    }
    if (barHumidityBox) barHumidityBox.className = 'realtime-tile px-2 py-1.5';
  }

  // 3. Lembab Tanah
  const barSoilEl = document.getElementById('barSoil');
  const barSoilSub = document.getElementById('barSoilSub');
  const barSoilBox = document.getElementById('barSoilBox');
  barSoilEl.textContent = `${soilNum.toFixed(0)} %`;
  if (soilNum < 35.0) {
    barSoilEl.className = 'text-xs sm:text-sm font-bold font-mono-num text-amber-300 mt-0.5';
    if (barSoilSub) {
      barSoilSub.textContent = 'Tanah Kering!';
      barSoilSub.className = 'text-[9px] text-amber-300 font-semibold truncate';
    }
    if (barSoilBox) barSoilBox.className = 'realtime-tile realtime-tile-warn px-2 py-1.5';
  } else {
    barSoilEl.className = 'text-xs sm:text-sm font-bold font-mono-num text-white mt-0.5';
    if (barSoilSub) {
      barSoilSub.textContent = 'Cukup Air';
      barSoilSub.className = 'text-[9px] text-emerald-400 font-medium truncate';
    }
    if (barSoilBox) barSoilBox.className = 'realtime-tile px-2 py-1.5';
  }

  // 4. Kondisi Cuaca
  const barSpikeEl = document.getElementById('barSpikeStatus');
  const barSpikeSub = document.getElementById('barSpikeSub');
  const barWeatherBox = document.getElementById('barWeatherBox');
  if (radar.is_spike) {
    barSpikeEl.textContent = 'Waspada';
    barSpikeEl.className = 'text-xs sm:text-sm font-bold text-sky-300 truncate mt-0.5';
    if (barSpikeSub) {
      barSpikeSub.textContent = 'Hujan ke Panas';
      barSpikeSub.className = 'text-[9px] text-sky-300 font-semibold truncate';
    }
    if (barWeatherBox) barWeatherBox.className = 'realtime-tile realtime-tile-alert px-2 py-1.5';
  } else {
    barSpikeEl.textContent = 'Stabil';
    barSpikeEl.className = 'text-xs sm:text-sm font-bold text-white truncate mt-0.5';
    if (barSpikeSub) {
      barSpikeSub.textContent = 'Cuaca Aman';
      barSpikeSub.className = 'text-[9px] text-emerald-400 font-medium truncate';
    }
    if (barWeatherBox) barWeatherBox.className = 'realtime-tile px-2 py-1.5';
  }

  const plotInput = document.getElementById('setPlotName');
  if (plotInput && document.activeElement !== plotInput) {
    plotInput.value = farm.plot_name || '';
  }
  const dateInput = document.getElementById('setPlantingDate');
  if (dateInput && document.activeElement !== dateInput) {
    dateInput.value = farm.planting_date || '';
  }
  const varInput = document.getElementById('setVariety');
  if (varInput && document.activeElement !== varInput) {
    varInput.value = farm.variety || 'Kangkung Daun Lebar';
  }
  const manHstInput = document.getElementById('setManualHst');
  if (manHstInput && document.activeElement !== manHstInput) {
    manHstInput.value =
      farm.manual_hst_override !== null && farm.manual_hst_override !== undefined
        ? farm.manual_hst_override
        : '';
  }

  const hwEsp = document.getElementById('hwEsp32LastSeen');
  if (hwEsp && data.hardware) {
    hwEsp.textContent = `Terhubung (${(data.hardware.esp32_last_seen || '').slice(11, 19) || 'Aktif'})`;
  }
}

/* ================= WIZARD STEP HELPER ================= */
function updateWizardSteps(stepNum) {
  const ids = ['wizStep1', 'wizStep2', 'wizStep3', 'wizStep4'];
  ids.forEach((id, idx) => {
    const el = document.getElementById(id);
    if (!el) return;
    const currentIdx = idx + 1;
    if (currentIdx < stepNum) {
      el.className = 'py-1 px-1 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-medium';
    } else if (currentIdx === stepNum) {
      el.className = 'py-1 px-1 rounded bg-slate-900 text-white border border-slate-900 font-semibold';
    } else {
      el.className = 'py-1 px-1 rounded bg-slate-50 text-slate-500 border border-slate-200';
    }
  });
}

/* ================= SINGLE CAMERA FRAME STATE MACHINE (STANDBY -> LIVE WEBCAM -> CAPTURE & AUTO-OFF) ================= */
function setElementVisibility(el, visible, displayStyle = 'block') {
  if (!el) return;
  if (visible) {
    el.classList.remove('hidden');
    el.style.display = displayStyle;
  } else {
    el.classList.add('hidden');
    el.style.display = 'none';
  }
}

function renderSingleCameraUI() {
  const singleStage = document.getElementById('singleCaptureStage');
  const dualResultStage = document.getElementById('dualResultPhotosStage');
  const badge = document.getElementById('singleStageBadge');
  const title = document.getElementById('singleStageTitle');
  const desc = document.getElementById('singleStageDesc');
  const topPill = document.getElementById('topConfirmedPill');
  const placeholder = document.getElementById('singleCameraPlaceholder');
  const phTitle = document.getElementById('singlePlaceholderTitle');
  const phSub = document.getElementById('singlePlaceholderSub');
  const liveStreamImg = document.getElementById('singleLiveStreamImg');
  const liveOverlayBadge = document.getElementById('liveStreamOverlayBadge');
  const liveBadgeText = document.getElementById('liveStreamBadgeText');
  const validationOverlayBadge = document.getElementById('validationOverlayBadge');
  const validationBadgeText = document.getElementById('validationBadgeText');
  const previewImg = document.getElementById('singlePreviewImg');
  const standbyBox = document.getElementById('singleActionStandbyBox');
  const btnTurnOnLabel = document.getElementById('btnTurnOnCameraLabel');
  const captureBox = document.getElementById('singleActionCaptureBox');
  const captureLabel = document.getElementById('btnSingleCaptureLabel');
  const validateBox = document.getElementById('singleActionValidateBox');
  const valPrompt = document.getElementById('validationPromptText');
  const confirmLabel = document.getElementById('btnConfirmPhotoLabel');
  const btnDeleteCapturedLabel = document.getElementById('btnDeleteCapturedLabel');

  // Auto-reconnect protection for live MJPEG stream
  if (liveStreamImg && !liveStreamImg._hasStreamErrorHandler) {
    liveStreamImg._hasStreamErrorHandler = true;
    liveStreamImg.addEventListener('error', () => {
      if (APP_STATE.capturePhase === 'TOP_LIVE' || APP_STATE.capturePhase === 'BOTTOM_LIVE') {
        setTimeout(() => {
          if (APP_STATE.capturePhase === 'TOP_LIVE' || APP_STATE.capturePhase === 'BOTTOM_LIVE') {
            const side = APP_STATE.capturePhase === 'TOP_LIVE' ? 'top' : 'bottom';
            liveStreamImg.src = `/api/v1/camera/stream?side=${side}&t=${Date.now()}`;
          }
        }, 1000);
      }
    });
  }

  // Mini Thumbnail Strip Elements
  const miniThumbTop = document.getElementById('miniThumbTop');
  const miniEmptyTop = document.getElementById('miniEmptyTop');
  const badgeStatusTop = document.getElementById('badgeStatusTop');
  const descStatusTop = document.getElementById('descStatusTop');
  const cardStatusTop = document.getElementById('cardStatusTop');

  const miniThumbBottom = document.getElementById('miniThumbBottom');
  const miniEmptyBottom = document.getElementById('miniEmptyBottom');
  const badgeStatusBottom = document.getElementById('badgeStatusBottom');
  const descStatusBottom = document.getElementById('descStatusBottom');
  const cardStatusBottom = document.getElementById('cardStatusBottom');

  const phase = APP_STATE.capturePhase;

  // Sync Mini Thumbnail Strip
  if (APP_STATE.topUrls && APP_STATE.topUrls.orig) {
    if (miniThumbTop) {
      miniThumbTop.src = APP_STATE.topUrls.orig;
      setElementVisibility(miniThumbTop, true);
    }
    setElementVisibility(miniEmptyTop, false);
    if (phase === 'TOP_VALIDATE') {
      if (badgeStatusTop) {
        badgeStatusTop.textContent = 'Memeriksa';
        badgeStatusTop.className = 'text-[9px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 shrink-0';
      }
      if (descStatusTop) descStatusTop.textContent = 'Sedang divalidasi';
      if (cardStatusTop) cardStatusTop.className = 'p-2 rounded-lg border-2 border-amber-400 bg-amber-50/40 flex items-center gap-2.5 transition';
    } else {
      if (badgeStatusTop) {
        badgeStatusTop.textContent = 'Tersimpan';
        badgeStatusTop.className = 'text-[9px] font-semibold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 shrink-0';
      }
      if (descStatusTop) descStatusTop.textContent = 'Foto atas siap';
      if (cardStatusTop) cardStatusTop.className = 'p-2 rounded-lg border border-emerald-300 bg-emerald-50/30 flex items-center gap-2.5 transition';
    }
  } else {
    setElementVisibility(miniThumbTop, false);
    setElementVisibility(miniEmptyTop, true, 'block');
    if (badgeStatusTop) {
      badgeStatusTop.textContent = phase === 'TOP_LIVE' ? 'Membidik' : 'Standby';
      badgeStatusTop.className = phase === 'TOP_LIVE'
        ? 'text-[9px] font-semibold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 shrink-0'
        : 'text-[9px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 shrink-0';
    }
    if (descStatusTop) descStatusTop.textContent = phase === 'TOP_LIVE' ? 'Kamera aktif' : 'Menunggu difoto';
    if (cardStatusTop) cardStatusTop.className = 'p-2 rounded-lg border border-slate-200 bg-white flex items-center gap-2.5 transition';
  }

  if (APP_STATE.bottomUrls && APP_STATE.bottomUrls.orig) {
    if (miniThumbBottom) {
      miniThumbBottom.src = APP_STATE.bottomUrls.orig;
      setElementVisibility(miniThumbBottom, true);
    }
    setElementVisibility(miniEmptyBottom, false);
    if (phase === 'BOTTOM_VALIDATE') {
      if (badgeStatusBottom) {
        badgeStatusBottom.textContent = 'Memeriksa';
        badgeStatusBottom.className = 'text-[9px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 shrink-0';
      }
      if (descStatusBottom) descStatusBottom.textContent = 'Sedang divalidasi';
      if (cardStatusBottom) cardStatusBottom.className = 'p-2 rounded-lg border-2 border-amber-400 bg-amber-50/40 flex items-center gap-2.5 transition';
    } else {
      if (badgeStatusBottom) {
        badgeStatusBottom.textContent = 'Tersimpan';
        badgeStatusBottom.className = 'text-[9px] font-semibold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 shrink-0';
      }
      if (descStatusBottom) descStatusBottom.textContent = 'Foto bawah siap';
      if (cardStatusBottom) cardStatusBottom.className = 'p-2 rounded-lg border border-emerald-300 bg-emerald-50/30 flex items-center gap-2.5 transition';
    }
  } else {
    setElementVisibility(miniThumbBottom, false);
    setElementVisibility(miniEmptyBottom, true, 'block');
    if (badgeStatusBottom) {
      badgeStatusBottom.textContent = phase === 'BOTTOM_LIVE' ? 'Membidik' : (phase === 'BOTTOM_STANDBY' ? 'Siap' : 'Menunggu');
      badgeStatusBottom.className = (phase === 'BOTTOM_LIVE' || phase === 'BOTTOM_STANDBY')
        ? 'text-[9px] font-semibold px-1.5 py-0.5 rounded bg-sky-100 text-sky-800 shrink-0'
        : 'text-[9px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 shrink-0';
    }
    if (descStatusBottom) {
      descStatusBottom.textContent = phase === 'BOTTOM_LIVE' ? 'Kamera aktif' : (phase === 'BOTTOM_STANDBY' ? 'Siap difoto' : 'Tahap 2');
    }
    if (cardStatusBottom) {
      cardStatusBottom.className = (phase === 'BOTTOM_STANDBY' || phase === 'BOTTOM_LIVE')
        ? 'p-2 rounded-lg border border-sky-300 bg-sky-50/30 flex items-center gap-2.5 transition'
        : 'p-2 rounded-lg border border-slate-200 bg-white flex items-center gap-2.5 transition';
    }
  }

  // State Transitions for Camera Frame
  if (phase === 'TOP_STANDBY') {
    updateWizardSteps(1);
    setElementVisibility(singleStage, true);
    setElementVisibility(dualResultStage, false);
    setElementVisibility(topPill, false);

    if (badge) {
      badge.textContent = 'TAHAP 1 DARI 2 • PERMUKAAN ATAS DAUN (KAMERA STANDBY)';
      badge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-700 border border-slate-300';
    }
    if (title) title.textContent = 'Siapkan Permukaan Atas Daun';
    if (desc) desc.textContent = 'Posisikan permukaan atas daun di bawah webcam, lalu tekan tombol "Nyalakan Kamera".';

    setElementVisibility(placeholder, true, 'flex');
    if (phTitle) phTitle.textContent = 'Kamera Dalam Posisi Standby (Hemat RAM UNO Q)';
    if (phSub) phSub.textContent = 'Tekan tombol "Nyalakan Kamera" di bawah saat daun sudah diletakkan di tatakan';

    setElementVisibility(liveStreamImg, false);
    if (liveStreamImg) liveStreamImg.src = '';
    setElementVisibility(liveOverlayBadge, false);

    setElementVisibility(previewImg, false);
    if (previewImg) previewImg.src = '';
    setElementVisibility(validationOverlayBadge, false);

    setElementVisibility(standbyBox, true);
    if (btnTurnOnLabel) btnTurnOnLabel.textContent = 'Nyalakan Kamera (Bagian Atas Daun)';
    setElementVisibility(captureBox, false);
    setElementVisibility(validateBox, false);

  } else if (phase === 'TOP_LIVE') {
    updateWizardSteps(1);
    setElementVisibility(singleStage, true);
    setElementVisibility(dualResultStage, false);
    setElementVisibility(topPill, false);

    if (badge) {
      badge.textContent = 'TAHAP 1 DARI 2 • LIVE WEBCAM DAUN ATAS AKTIF';
      badge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200';
    }
    if (title) title.textContent = 'Bidikan Real-Time Bagian Atas Daun';
    if (desc) desc.textContent = 'Pastikan posisi daun atas sudah pas dan fokus, lalu tekan "Ambil Foto Daun Atas".';

    setElementVisibility(placeholder, false);
    setElementVisibility(previewImg, false);
    if (previewImg) previewImg.src = '';
    setElementVisibility(validationOverlayBadge, false);

    if (liveStreamImg) {
      liveStreamImg.src = `/api/v1/camera/stream?side=top&t=${Date.now()}`;
      setElementVisibility(liveStreamImg, true);
    }
    setElementVisibility(liveOverlayBadge, true, 'flex');
    if (liveBadgeText) liveBadgeText.textContent = 'LIVE WEBCAM • DAUN ATAS';

    setElementVisibility(standbyBox, false);
    setElementVisibility(captureBox, true, 'grid');
    if (captureLabel) captureLabel.textContent = 'Ambil Foto Daun Atas';
    setElementVisibility(validateBox, false);

  } else if (phase === 'TOP_VALIDATE') {
    updateWizardSteps(1);
    setElementVisibility(singleStage, true);
    setElementVisibility(dualResultStage, false);
    setElementVisibility(topPill, false);

    if (badge) {
      badge.textContent = 'VALIDASI FOTO 1 • PERIKSA HASIL FOTO DAUN ATAS';
      badge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-300';
    }
    if (title) title.textContent = 'Periksa Hasil Foto Daun Atas';
    if (desc) desc.textContent = 'Foto berhasil dikunci dan kamera telah dimatikan otomatis. Pastikan kejelasan gambar.';

    setElementVisibility(placeholder, false);
    setElementVisibility(liveStreamImg, false);
    if (liveStreamImg) liveStreamImg.src = '';
    setElementVisibility(liveOverlayBadge, false);

    // Tampilkan hasil foto tangkapan tepat di dalam frame kamera
    if (previewImg && APP_STATE.topUrls && APP_STATE.topUrls.orig) {
      previewImg.src = APP_STATE.topUrls.orig;
      setElementVisibility(previewImg, true);
    }
    setElementVisibility(validationOverlayBadge, true, 'flex');
    if (validationBadgeText) validationBadgeText.textContent = 'PRATINJAU TERSIMPAN • FOTO DAUN ATAS';

    setElementVisibility(standbyBox, false);
    setElementVisibility(captureBox, false);
    setElementVisibility(validateBox, true);
    if (valPrompt) valPrompt.textContent = 'Apakah hasil foto daun bagian atas ini sudah jelas dan tepat?';
    if (confirmLabel) confirmLabel.textContent = 'Sudah Tepat, Lanjut Foto Bawah';
    if (btnDeleteCapturedLabel) btnDeleteCapturedLabel.textContent = 'Ambil Ulang Foto Daun Atas';

  } else if (phase === 'BOTTOM_STANDBY') {
    updateWizardSteps(2);
    setElementVisibility(singleStage, true);
    setElementVisibility(dualResultStage, false);
    setElementVisibility(topPill, true);

    if (badge) {
      badge.textContent = 'TAHAP 2 DARI 2 • BALIK DAUN KE BAGIAN BAWAH (STANDBY)';
      badge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-50 text-sky-800 border border-sky-200';
    }
    if (title) title.textContent = 'Balik Daun & Siapkan Bagian Bawah Daun';
    if (desc) desc.textContent = 'Balik daun pada tatakan untuk memeriksa permukaan bawah, lalu tekan tombol "Nyalakan Kamera".';

    setElementVisibility(placeholder, true, 'flex');
    if (phTitle) phTitle.textContent = 'Foto Daun Atas Tersimpan • Siapkan Daun Bawah';
    if (phSub) phSub.textContent = 'Setelah daun dibalik menghadap webcam, tekan "Nyalakan Kamera" di bawah';

    setElementVisibility(liveStreamImg, false);
    if (liveStreamImg) liveStreamImg.src = '';
    setElementVisibility(liveOverlayBadge, false);

    setElementVisibility(previewImg, false);
    if (previewImg) previewImg.src = '';
    setElementVisibility(validationOverlayBadge, false);

    setElementVisibility(standbyBox, true);
    if (btnTurnOnLabel) btnTurnOnLabel.textContent = 'Nyalakan Kamera (Bagian Bawah Daun)';
    setElementVisibility(captureBox, false);
    setElementVisibility(validateBox, false);

  } else if (phase === 'BOTTOM_LIVE') {
    updateWizardSteps(2);
    setElementVisibility(singleStage, true);
    setElementVisibility(dualResultStage, false);
    setElementVisibility(topPill, true);

    if (badge) {
      badge.textContent = 'TAHAP 2 DARI 2 • LIVE WEBCAM DAUN BAWAH AKTIF';
      badge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-50 text-sky-800 border border-sky-200';
    }
    if (title) title.textContent = 'Bidikan Real-Time Bagian Bawah Daun';
    if (desc) desc.textContent = 'Pastikan permukaan bawah daun terlihat jelas, lalu tekan "Ambil Foto Daun Bawah".';

    setElementVisibility(placeholder, false);
    setElementVisibility(previewImg, false);
    if (previewImg) previewImg.src = '';
    setElementVisibility(validationOverlayBadge, false);

    if (liveStreamImg) {
      liveStreamImg.src = `/api/v1/camera/stream?side=bottom&t=${Date.now()}`;
      setElementVisibility(liveStreamImg, true);
    }
    setElementVisibility(liveOverlayBadge, true, 'flex');
    if (liveBadgeText) liveBadgeText.textContent = 'LIVE WEBCAM • DAUN BAWAH';

    setElementVisibility(standbyBox, false);
    setElementVisibility(captureBox, true, 'grid');
    if (captureLabel) captureLabel.textContent = 'Ambil Foto Daun Bawah';
    setElementVisibility(validateBox, false);

  } else if (phase === 'BOTTOM_VALIDATE') {
    updateWizardSteps(2);
    setElementVisibility(singleStage, true);
    setElementVisibility(dualResultStage, false);
    setElementVisibility(topPill, true);

    if (badge) {
      badge.textContent = 'VALIDASI FOTO 2 • PERIKSA HASIL FOTO DAUN BAWAH';
      badge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-300';
    }
    if (title) title.textContent = 'Periksa Hasil Foto Daun Bawah';
    if (desc) desc.textContent = 'Foto daun bawah berhasil dikunci dan kamera dimatikan. Periksa apakah foto sudah jelas.';

    setElementVisibility(placeholder, false);
    setElementVisibility(liveStreamImg, false);
    if (liveStreamImg) liveStreamImg.src = '';
    setElementVisibility(liveOverlayBadge, false);

    // Tampilkan hasil foto tangkapan daun bawah tepat di dalam frame kamera
    if (previewImg && APP_STATE.bottomUrls && APP_STATE.bottomUrls.orig) {
      previewImg.src = APP_STATE.bottomUrls.orig;
      setElementVisibility(previewImg, true);
    }
    setElementVisibility(validationOverlayBadge, true, 'flex');
    if (validationBadgeText) validationBadgeText.textContent = 'PRATINJAU TERSIMPAN • FOTO DAUN BAWAH';

    setElementVisibility(standbyBox, false);
    setElementVisibility(captureBox, false);
    setElementVisibility(validateBox, true);
    if (valPrompt) valPrompt.textContent = 'Apakah hasil foto daun bagian bawah ini sudah jelas dan tepat?';
    if (confirmLabel) confirmLabel.textContent = 'Sudah Tepat, Analisis Kesehatan Kangkung';
    if (btnDeleteCapturedLabel) btnDeleteCapturedLabel.textContent = 'Ambil Ulang Foto Daun Bawah';

  } else {
    // PROCESSING & DONE
    if (liveStreamImg) {
      liveStreamImg.src = '';
      setElementVisibility(liveStreamImg, false);
    }
    setElementVisibility(liveOverlayBadge, false);
    setElementVisibility(validationOverlayBadge, false);
    setElementVisibility(singleStage, false);
    setElementVisibility(dualResultStage, true);
  }
}

function triggerSingleFlash() {
  const flashEl = document.getElementById('singleShutterFlash');
  if (!flashEl) return;
  flashEl.classList.remove('trigger');
  void flashEl.offsetWidth;
  flashEl.classList.add('trigger');
}

async function startLiveWebcam() {
  const isTop = APP_STATE.capturePhase === 'TOP_STANDBY';
  const side = isTop ? 'top' : 'bottom';
  try {
    await fetch('/api/v1/camera/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ side }),
    });
    APP_STATE.capturePhase = isTop ? 'TOP_LIVE' : 'BOTTOM_LIVE';
    renderSingleCameraUI();
  } catch (err) {
    console.error('Failed to start live webcam:', err);
    showToast('Gagal menyalakan kamera.');
  }
}

async function stopLiveWebcamToStandby(silent = false) {
  const isTop = APP_STATE.capturePhase === 'TOP_LIVE' || APP_STATE.capturePhase === 'TOP_STANDBY';
  const liveStreamImg = document.getElementById('singleLiveStreamImg');
  if (liveStreamImg) {
    liveStreamImg.src = '';
    setElementVisibility(liveStreamImg, false);
  }
  try {
    await fetch('/api/v1/camera/stop', { method: 'POST' });
  } catch (err) {
    console.error('Stop camera error:', err);
  }
  APP_STATE.capturePhase = isTop ? 'TOP_STANDBY' : 'BOTTOM_STANDBY';
  renderSingleCameraUI();
  if (!silent) {
    showToast('Kamera dimatikan (Webcam & Lampu LED Mati).');
  }
}

async function handleSingleFrameCapture() {
  const isTop = APP_STATE.capturePhase === 'TOP_LIVE' || APP_STATE.capturePhase === 'TOP_STANDBY';
  const side = isTop ? 'top' : 'bottom';
  triggerSingleFlash();

  try {
    const formData = new FormData();
    const res = await fetch(`/api/v1/capture/${side}`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const errBody = await res.text();
      console.error(`Capture HTTP error ${res.status}:`, errBody);
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    const cacheBusted = `${data.image_url}?t=${Date.now()}`;

    // Putus stream di browser karena kamera di backend sudah otomatis di-release
    const liveStreamImg = document.getElementById('singleLiveStreamImg');
    if (liveStreamImg) {
      liveStreamImg.src = '';
      setElementVisibility(liveStreamImg, false);
    }

    if (isTop) {
      APP_STATE.topUrls = { orig: cacheBusted, mask: null, stage: null };
      APP_STATE.capturePhase = 'TOP_VALIDATE';
    } else {
      APP_STATE.bottomUrls = { orig: cacheBusted, mask: null, stage: null };
      APP_STATE.capturePhase = 'BOTTOM_VALIDATE';
    }
    renderSingleCameraUI();
  } catch (err) {
    console.error('Capture error:', err);
    showToast('Gagal mengambil foto dari kamera.');
  }
}

function deleteCurrentCapturedPhoto() {
  if (APP_STATE.capturePhase === 'TOP_VALIDATE') {
    APP_STATE.topUrls = { orig: null, mask: null, stage: null };
    APP_STATE.capturePhase = 'TOP_STANDBY';
    renderSingleCameraUI();
    showToast('Foto daun atas dihapus. Klik "Nyalakan Kamera" untuk memotret ulang daun atas.');
  } else if (APP_STATE.capturePhase === 'BOTTOM_VALIDATE') {
    APP_STATE.bottomUrls = { orig: null, mask: null, stage: null };
    APP_STATE.capturePhase = 'BOTTOM_STANDBY';
    renderSingleCameraUI();
    showToast('Foto daun bawah dihapus. Klik "Nyalakan Kamera" untuk memotret ulang daun bawah (Foto daun atas tetap tersimpan).');
  }
}

async function confirmCurrentCapturedPhoto() {
  if (APP_STATE.capturePhase === 'TOP_VALIDATE') {
    APP_STATE.capturePhase = 'BOTTOM_STANDBY';
    renderSingleCameraUI();
    showToast('Foto daun atas tersimpan. Balik daun ke bagian bawah, lalu klik "Nyalakan Kamera".');
  } else if (APP_STATE.capturePhase === 'BOTTOM_VALIDATE') {
    APP_STATE.capturePhase = 'PROCESSING';
    renderSingleCameraUI();
    await triggerDualAnalysisWithAnimation();
  }
}

/* ================= STEP 3: AUTOMATIC 5-STAGE AI SCANNING ANIMATION ================= */
function setScanStepVisual(stepIdx, state) {
  const el = document.getElementById(`stepStage${stepIdx}`);
  if (!el) return;
  el.classList.remove('active', 'done');
  if (state === 'active') {
    el.classList.add('active');
  } else if (state === 'done') {
    el.classList.add('done');
  }
}

async function triggerDualAnalysisWithAnimation() {
  updateWizardSteps(3);

  const imgTop = document.getElementById('imgTopPreview');
  const imgBot = document.getElementById('imgBottomPreview');
  if (APP_STATE.topUrls.orig) imgTop.src = APP_STATE.topUrls.orig;
  if (APP_STATE.bottomUrls.orig) imgBot.src = APP_STATE.bottomUrls.orig;

  document.getElementById('badgeTopState').textContent = 'Memindai...';
  document.getElementById('badgeBottomState').textContent = 'Memindai...';

  const vpTop = document.getElementById('viewportTop');
  const vpBot = document.getElementById('viewportBottom');
  const scanCard = document.getElementById('scanningProgressCard');
  const resContainer = document.getElementById('decisionResultContainer');
  const progBar = document.getElementById('scanProgressBar');
  const timerTxt = document.getElementById('scanTimerText');

  resContainer.classList.add('hidden');
  scanCard.classList.remove('hidden');
  vpTop.classList.add('is-scanning');
  vpBot.classList.add('is-scanning');

  for (let i = 1; i <= 5; i++) setScanStepVisual(i, 'pending');

  const analysisPromise = fetch('/api/v1/analyze-dual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  }).then((r) => r.json());

  const stagePercentages = [20, 42, 68, 86, 100];
  for (let s = 1; s <= 5; s++) {
    setScanStepVisual(s, 'active');
    progBar.style.width = `${stagePercentages[s - 1]}%`;
    timerTxt.textContent = `${stagePercentages[s - 1]}%`;
    await sleep(270);
    setScanStepVisual(s, 'done');
  }

  try {
    const result = await analysisPromise;
    APP_STATE.latestAnalysis = result;
    APP_STATE.capturePhase = 'DONE';

    vpTop.classList.remove('is-scanning');
    vpBot.classList.remove('is-scanning');
    await sleep(150);
    scanCard.classList.add('hidden');

    const ts = Date.now();
    APP_STATE.topUrls = {
      orig: `${result.img_top_orig}?t=${ts}`,
      mask: `${result.img_top_mask}?t=${ts}`,
      stage: `${result.img_top_stage}?t=${ts}`,
    };
    APP_STATE.bottomUrls = {
      orig: `${result.img_bottom_orig}?t=${ts}`,
      mask: `${result.img_bottom_mask}?t=${ts}`,
      stage: `${result.img_bottom_stage}?t=${ts}`,
    };

    switchSurfaceView('top', 'mask');
    switchSurfaceView('bottom', 'mask');

    updateWizardSteps(4);
    renderDecisionResult(result);
    loadStatusAndHeader();
  } catch (err) {
    console.error('Analysis error:', err);
    vpTop.classList.remove('is-scanning');
    vpBot.classList.remove('is-scanning');
    scanCard.classList.add('hidden');
    showToast('Gagal memproses analisis citra.');
  }
}

function switchSurfaceView(side, mode) {
  const urls = side === 'top' ? APP_STATE.topUrls : APP_STATE.bottomUrls;
  const imgEl = document.getElementById(side === 'top' ? 'imgTopPreview' : 'imgBottomPreview');
  if (imgEl && urls[mode]) {
    imgEl.src = urls[mode];
  }

  const prefix = side === 'top' ? 'btnViewTop-' : 'btnViewBottom-';
  ['orig', 'mask', 'stage'].forEach((m) => {
    const btn = document.getElementById(`${prefix}${m}`);
    if (!btn) return;
    if (m === mode) {
      btn.className = 'seg-btn active py-1 rounded';
    } else {
      btn.className = 'seg-btn py-1 rounded';
    }
  });
}

/* ================= STEP 4: RENDER DECISION & SOLUTION REPORT ================= */
function renderDecisionResult(res) {
  const container = document.getElementById('decisionResultContainer');
  const card = document.getElementById('decisionMainCard');
  container.classList.remove('hidden');

  const level = res.decision_level || 'SAFE';
  card.className = `decision-banner decision-${level} p-4 space-y-4 shadow-sm`;

  const codeBadge = document.getElementById('resDecisionCodeBadge');
  codeBadge.className = `status-pill-${level} px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide`;
  codeBadge.textContent = `${res.decision_code || 'STATUS'} • UMUR ${res.hst} HARI`;

  document.getElementById('resLatencyBadge').textContent =
    `Waktu proses: ${Number(res.latency_ms || 42).toFixed(0)} ms`;
  document.getElementById('resDecisionTitle').textContent = res.decision_title || '';

  const sevFinalEl = document.getElementById('resSeverityFinal');
  const sevTopNum = Number(res.severity_top || 0);
  const sevBotNum = Number(res.severity_bottom || 0);
  const sevFinalNum = Number(res.severity_final || 0);

  sevFinalEl.textContent = `${sevFinalNum.toFixed(1)}%`;
  document.getElementById('resSeverityCategory').textContent = res.severity_category || '';

  // 1. Isi Tabel Penjelasan Hasil Pemeriksaan dengan Bahasa Mudah Dipahami
  const rowTop = document.getElementById('tableRowTopLeaf');
  if (sevTopNum <= 0.0) {
    rowTop.innerHTML = `<strong class="font-mono-num text-emerald-800">0% rusak</strong> — Permukaan atas daun hijau sehat, tidak ditemukan bercak.`;
  } else {
    rowTop.innerHTML = `<strong class="font-mono-num text-amber-800">${sevTopNum.toFixed(1)}% rusak</strong> — Ditemukan bercak kuning/coklat pada permukaan atas daun.`;
  }

  const rowBot = document.getElementById('tableRowBottomLeaf');
  const pm = res.pipeline_metrics || {};
  const topDet = pm.top_details || {};
  const botDet = pm.bottom_details || {};
  const hasWhitePustules = Number(botDet.white_pustule_px || 0) > 15;

  if (sevBotNum <= 0.0) {
    rowBot.innerHTML = `<strong class="font-mono-num text-emerald-800">0% rusak</strong> — Bagian bawah daun bersih, tidak ditemukan bintil putih.`;
  } else if (hasWhitePustules) {
    rowBot.innerHTML = `<strong class="font-mono-num text-red-700">${sevBotNum.toFixed(1)}% rusak</strong> — Ditemukan bintil-bintil putih (jamur Brontok) di balik daun.`;
  } else {
    rowBot.innerHTML = `<strong class="font-mono-num text-amber-800">${sevBotNum.toFixed(1)}% rusak</strong> — Ditemukan bercak kerusakan pada bagian bawah daun.`;
  }

  const rowPathogen = document.getElementById('tableRowPathogen');
  rowPathogen.textContent = `${res.pathogen_detected || 'Tidak Ada Penyakit'} (${res.severity_category || 'Sehat'})`;

  const soilNum = Number(res.soil_moisture || 62);
  const tempNum = Number(res.temperature || 28.8);
  const rhNum = Number(res.humidity || 73);
  const soilLabel = soilNum < 35.0 ? 'Tanah Kering / Kurang Air' : 'Cukup Air';
  const weatherLabel = res.post_rain_heat_spike ? 'Waspada Habis Hujan Langsung Panas' : 'Cuaca Stabil';

  document.getElementById('tableRowEnvironment').innerHTML =
    `Lembab Tanah <strong class="font-mono-num">${soilNum.toFixed(0)}%</strong> (${soilLabel}) • Suhu Udara <strong class="font-mono-num">${tempNum.toFixed(1)}°C</strong> • Lembab Udara <strong class="font-mono-num">${rhNum.toFixed(0)}%</strong> (${weatherLabel})`;

  const phaseText = res.hst <= 7 ? 'Fase Bibit' : res.hst <= 15 ? 'Fase Remaja' : 'Fase Siap Panen (Dilarang Semprot Kimia)';
  document.getElementById('tableRowPlantAge').innerHTML =
    `<strong>Umur ${res.hst} Hari</strong> (${phaseText}) • ${res.variety || 'Kangkung Daun Lebar'}`;

  document.getElementById('resRecommendationText').textContent = res.recommendation || '';
  document.getElementById('resEconomicBadge').textContent = pm.economic_impact || '';

  // 2. Isi Daftar Langkah Solusi Petani
  const stepsList = document.getElementById('resActionStepsList');
  stepsList.innerHTML = '';
  (res.action_steps || []).forEach((step, idx) => {
    const li = document.createElement('li');
    li.className = 'flex items-start gap-2.5 bg-slate-50 p-2.5 rounded-lg border border-slate-200/80';
    li.innerHTML = `
      <span class="w-4 h-4 rounded bg-slate-200 text-slate-800 text-[10px] font-bold font-mono-num flex items-center justify-center shrink-0 mt-0.5">${idx + 1}</span>
      <span class="leading-relaxed text-slate-700">${step}</span>
    `;
    stepsList.appendChild(li);
  });

  // 3. Isi Tabel Rincian Pemrosesan Gambar AI (Mudah Dipahami namun Akurat Sesuai Pemrosesan)
  const proofEl = document.getElementById('resTechnicalProof');
  const totalNoiseRemoved = (topDet.removed_speckles || 0) + (botDet.removed_speckles || 0);
  const totalShadowRemoved = (topDet.removed_shadows || 0) + (botDet.removed_shadows || 0);
  const confTop = Number(res.gating_top_conf || 99.1).toFixed(1);
  const confBot = Number(res.gating_bottom_conf || 99.2).toFixed(1);

  proofEl.innerHTML = `
    <div class="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <table class="w-full text-left border-collapse text-[11px]">
        <tbody class="divide-y divide-slate-200">
          <tr>
            <td class="py-2 px-2.5 font-semibold text-slate-600 bg-slate-50 w-2/5">Tingkat Keyakinan AI</td>
            <td class="py-2 px-2.5 text-slate-800">
              Foto Atas: <strong class="font-mono-num">${confTop}%</strong> • Foto Bawah: <strong class="font-mono-num">${confBot}%</strong>
            </td>
          </tr>
          <tr>
            <td class="py-2 px-2.5 font-semibold text-slate-600 bg-slate-50">Pemisahan Latar Belakang</td>
            <td class="py-2 px-2.5 text-slate-800">
              Berhasil memisahkan daun dari latar (Luas daun atas: <strong class="font-mono-num">${topDet.total_leaf_px || '--'} piksel</strong>, bawah: <strong class="font-mono-num">${botDet.total_leaf_px || '--'} piksel</strong>)
            </td>
          </tr>
          <tr>
            <td class="py-2 px-2.5 font-semibold text-slate-600 bg-slate-50">Area Penyakit Terdeteksi</td>
            <td class="py-2 px-2.5 text-slate-800">
              Atas: <strong class="font-mono-num">${topDet.lesion_px || 0} piksel</strong> bercak • Bawah: <strong class="font-mono-num">${botDet.lesion_px || 0} piksel</strong> (Bintil putih: <strong class="font-mono-num">${botDet.white_pustule_px || 0} piksel</strong>)
            </td>
          </tr>
          <tr>
            <td class="py-2 px-2.5 font-semibold text-slate-600 bg-slate-50">Filter Bayangan &amp; Kotoran</td>
            <td class="py-2 px-2.5 text-slate-800">
              Mengabaikan <strong class="font-mono-num">${totalNoiseRemoved} titik</strong> bintik kotoran kecil dan <strong class="font-mono-num">${totalShadowRemoved} area</strong> bayangan gelap agar hasil akurat
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  `;

  document.getElementById('badgeTopState').textContent = `Kerusakan: ${sevTopNum.toFixed(1)}%`;
  document.getElementById('badgeBottomState').textContent = `Kerusakan: ${sevBotNum.toFixed(1)}%`;
}

async function resetInspectionSession() {
  await fetch('/api/v1/capture/reset', { method: 'POST' });
  APP_STATE.topUrls = { orig: null, mask: null, stage: null };
  APP_STATE.bottomUrls = { orig: null, mask: null, stage: null };
  APP_STATE.capturePhase = 'TOP_STANDBY';

  document.getElementById('decisionResultContainer').classList.add('hidden');
  document.getElementById('scanningProgressCard').classList.add('hidden');
  renderSingleCameraUI();
}

/* ================= MENU 2: MIKROKLIMAT & LEMBAB TANAH ================= */
async function loadTelemetryAndChart() {
  try {
    const res = await fetch('/api/v1/telemetry/history?limit=25');
    const data = await res.json();
    const latest = data.latest || {};
    const radar = data.weather_radar || {};
    const hstInfo = data.hst_info || {};
    const history = data.history || [];

    const soil = Number(latest.soil_moisture || 62.0);
    const soilValEl = document.getElementById('landSoilValue');
    const soilBadge = document.getElementById('landSoilBadge');
    const soilProg = document.getElementById('landSoilProgress');
    const soilStatus = document.getElementById('landSoilStatusText');

    soilValEl.textContent = `${soil.toFixed(0)}%`;
    soilProg.style.width = `${Math.min(100, Math.max(5, soil))}%`;

    if (soil < 35.0) {
      soilProg.className = 'h-full bg-amber-500 transition-all duration-500';
      soilBadge.textContent = 'PERLU DISIRAM';
      soilBadge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase status-pill-WARNING_WATER';
      soilStatus.className = 'text-xs font-semibold text-amber-800 pt-0.5';
      soilStatus.textContent = 'Tanah kering (<35%). Segera siram air, jangan semprot pestisida.';
    } else if (soil <= 75.0) {
      soilProg.className = 'h-full bg-emerald-700 transition-all duration-500';
      soilBadge.textContent = 'CUKUP AIR';
      soilBadge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase status-pill-SAFE';
      soilStatus.className = 'text-xs font-medium text-slate-700 pt-0.5';
      soilStatus.textContent = 'Tanah cukup lembab. Tanaman tidak kekurangan air.';
    } else {
      soilProg.className = 'h-full bg-sky-700 transition-all duration-500';
      soilBadge.textContent = 'SANGAT BASAH';
      soilBadge.className = 'inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase status-pill-INFO_WEATHER';
      soilStatus.className = 'text-xs font-medium text-slate-700 pt-0.5';
      soilStatus.textContent = 'Tanah sudah sangat basah. Tunda penyiraman berikutnya.';
    }

    document.getElementById('landHstTag').textContent = `Umur ${hstInfo.hst || 16} Hari (${hstInfo.phase_short || ''})`;
    document.getElementById('landWateringFreq').textContent = hstInfo.watering_freq || '';

    const spikeBadge = document.getElementById('landSpikeBadge');
    const spikeSummary = document.getElementById('landSpikeSummary');
    document.getElementById('landCurrentTemp').textContent = `${Number(latest.temperature || 28.8).toFixed(1)} °C`;
    document.getElementById('landCurrentRh').textContent = `${Number(latest.humidity || 73.0).toFixed(0)} %`;

    if (radar.is_spike) {
      spikeBadge.textContent = 'WASPADA CUACA BRONTOK';
      spikeBadge.className = 'px-2.5 py-1 rounded text-[10px] font-bold uppercase status-pill-INFO_WEATHER';
      spikeSummary.textContent =
        'Terdeteksi habis lembab/hujan langsung panas terik. Hindari menyiram daun pada sore atau malam hari agar jamur putih tidak tumbuh.';
    } else {
      spikeBadge.textContent = 'CUACA AMAN';
      spikeBadge.className = 'px-2.5 py-1 rounded text-[10px] font-bold uppercase status-pill-SAFE';
      spikeSummary.textContent =
        'Cuaca kebun stabil. Tidak ada perubahan ekstrem dari hujan ke panas terik.';
    }

    const labels = history.map((r) => (r.timestamp || '').slice(11, 16));
    const soils = history.map((r) => Number(r.soil_moisture || 0));
    const barColors = soils.map((val) => (val < 35.0 ? '#f59e0b' : '#15803d'));

    // 1. Tampilkan Catatan Pembacaan Ringkas 5 Waktu Terakhir (Selalu dieksekusi pertama)
    const simpleList = document.getElementById('telemetrySimpleList');
    if (simpleList) {
      simpleList.innerHTML = '';
      const recentFive = history.slice(-5).reverse();
      recentFive.forEach((r) => {
        const sVal = Number(r.soil_moisture || 0);
        const isDry = sVal < 35.0;
        const rowEl = document.createElement('div');
        rowEl.className = 'flex items-center justify-between px-3 py-2';
        rowEl.innerHTML = `
          <div class="font-mono-num font-semibold text-slate-700">${formatWibTimestamp(r.timestamp)}</div>
          <div class="flex items-center gap-3">
            <span class="text-slate-600">Suhu <strong class="font-mono-num text-slate-900">${Number(r.temperature).toFixed(1)}°C</strong></span>
            <span class="px-2 py-0.5 rounded text-[11px] font-semibold ${
              isDry ? 'status-pill-WARNING_WATER' : 'status-pill-SAFE'
            }">
              Tanah ${sVal.toFixed(0)}% (${isDry ? 'Kering' : 'Cukup Air'})
            </span>
          </div>
        `;
        simpleList.appendChild(rowEl);
      });
    }

    // 2. Mengisi Tabel Riwayat Lengkap Nilai Sensor ESP32 (Kebal terhadap kegagalan CDN Chart)
    const tableBody = document.getElementById('telemetryHistoryTableBody');
    if (tableBody) {
      if (!history || history.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="6" class="py-3 px-3 text-center text-slate-400">Belum ada data sensor tercatat di database.</td></tr>';
      } else {
        tableBody.innerHTML = '';
        const recentRows = history.slice(-20).reverse();
        recentRows.forEach((r) => {
          const sVal = Number(r.soil_moisture || 0);
          const isDry = sVal < 35.0;
          const tr = document.createElement('tr');
          tr.className = 'hover:bg-slate-50 transition-colors';
          tr.innerHTML = `
            <td class="py-2 px-3 font-mono-num text-slate-700 whitespace-nowrap font-medium">${formatWibTimestamp(r.timestamp)}</td>
            <td class="py-2 px-3 font-mono-num font-semibold text-slate-800">${Number(r.temperature || 0).toFixed(1)} °C</td>
            <td class="py-2 px-3 font-mono-num text-slate-700">${Number(r.humidity || 0).toFixed(1)} %</td>
            <td class="py-2 px-3 font-mono-num font-semibold ${isDry ? 'text-amber-800' : 'text-emerald-800'}">${sVal.toFixed(1)} %</td>
            <td class="py-2 px-3 font-mono-num text-slate-500">${r.adc_raw || '-'}</td>
            <td class="py-2 px-3">
              <span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase ${isDry ? 'status-pill-WARNING_WATER' : 'status-pill-SAFE'}">
                ${isDry ? 'Perlu Disiram' : 'Cukup Air'}
              </span>
            </td>
          `;
          tableBody.appendChild(tr);
        });
      }
    }

    // 3. Render Grafik Batang (Diproteksi dalam blok aman jika CDN Chart.js offline/terputus)
    try {
      if (typeof Chart !== 'undefined') {
        const ctx = document.getElementById('telemetryChart');
        if (ctx) {
          if (APP_STATE.telemetryChartInstance) {
            APP_STATE.telemetryChartInstance.destroy();
          }
          APP_STATE.telemetryChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
              labels,
              datasets: [
                {
                  label: 'Lembab Tanah (%)',
                  data: soils,
                  backgroundColor: barColors,
                  borderRadius: 4,
                  maxBarThickness: 28,
                },
              ],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: { display: false },
                tooltip: {
                  callbacks: {
                    label: (item) => {
                      const idx = item.dataIndex;
                      const row = history[idx] || {};
                      const statusTxt = item.raw < 35 ? 'Kering (Perlu Siram)' : 'Cukup Air (Aman)';
                      return `Lembab Tanah: ${item.raw}% — ${statusTxt} | Suhu: ${row.temperature || '--'}°C`;
                    },
                  },
                },
              },
              scales: {
                x: {
                  ticks: { color: '#64748b', font: { size: 10 } },
                  grid: { display: false },
                },
                y: {
                  min: 0,
                  max: 100,
                  ticks: {
                    color: '#64748b',
                    font: { size: 10 },
                    stepSize: 25,
                    callback: (v) => v + '%',
                  },
                  grid: { color: '#f1f5f9' },
                },
              },
            },
          });
        }
      }
    } catch (chartErr) {
      console.warn('Chart.js render deferred or unavailable:', chartErr);
    }
  } catch (err) {
    console.error('Error loading telemetry chart:', err);
  }
}

function updateCsvDownloadLink() {
  const sel = document.getElementById('csvTimeRangeSelect');
  const btn = document.getElementById('btnDownloadCsv');
  if (sel && btn) {
    btn.href = `/api/v1/telemetry/export.csv?range=${sel.value}`;
  }
}

/* ================= MENU 3: RIWAYAT & PERKEMBANGAN KESEHATAN DAUN ================= */
async function loadInspectionHistory() {
  try {
    const res = await fetch('/api/v1/history?limit=15');
    const data = await res.json();
    const records = data.records || [];
    const trend = data.trend || [];

    // 1. Buat Kesimpulan Tren Otomatis yang Mudah Dipahami
    const summaryBox = document.getElementById('historyTrendSummaryBox');
    if (summaryBox) {
      if (trend.length === 0) {
        summaryBox.textContent = 'Belum ada riwayat pemeriksaan daun.';
      } else if (trend.length === 1) {
        const only = trend[0];
        summaryBox.innerHTML = `Pemeriksaan terakhir pada <strong>Umur ${only.hst} Hari</strong> mencatat tingkat kerusakan daun sebesar <strong>${Number(only.severity_final).toFixed(1)}%</strong>.`;
      } else {
        const prev = trend[trend.length - 2];
        const last = trend[trend.length - 1];
        const diff = Number(last.severity_final) - Number(prev.severity_final);
        if (Number(last.severity_final) === 0) {
          summaryBox.innerHTML = `<strong>Kesimpulan Riwayat:</strong> Kondisi daun pada pemeriksaan terakhir <strong>Sehat (0% kerusakan)</strong>. Pertahankan pola penyiraman sesuai jadwal.`;
        } else if (diff > 0.5) {
          summaryBox.innerHTML = `<strong>Kesimpulan Riwayat:</strong> Kerusakan daun <strong>meningkat dari ${Number(prev.severity_final).toFixed(1)}% menjadi ${Number(last.severity_final).toFixed(1)}%</strong> pada pemeriksaan terakhir (Umur ${last.hst} Hari). Penyakit menyebar cepat, segera jalankan rekomendasi tindakan di bawah.`;
        } else if (diff < -0.5) {
          summaryBox.innerHTML = `<strong>Kesimpulan Riwayat:</strong> Kerusakan daun <strong>menurun dari ${Number(prev.severity_final).toFixed(1)}% menjadi ${Number(last.severity_final).toFixed(1)}%</strong>. Kondisi tanaman mulai membaik.`;
        } else {
          summaryBox.innerHTML = `<strong>Kesimpulan Riwayat:</strong> Tingkat kerusakan daun stabil di kisaran <strong>${Number(last.severity_final).toFixed(1)}%</strong> pada Umur ${last.hst} Hari.`;
        }
      }
    }

    // 2. Diagram Batang Berwarna Berdasarkan Tingkat Kerusakan
    const ctx = document.getElementById('severityTrendChart');
    if (ctx) {
      if (APP_STATE.severityChartInstance) {
        APP_STATE.severityChartInstance.destroy();
      }
      const barValues = trend.map((t) => {
        const v = Number(t.severity_final || 0);
        // Beri tinggi minimal 0.4 agar bar Sehat (0%) tetap terlihat sedikit garis hijaunya
        return v === 0 ? 0.4 : v;
      });
      const barColors = trend.map((t) => {
        const v = Number(t.severity_final || 0);
        if (v <= 0.0) return '#15803d'; // Hijau Sehat
        if (v <= 5.0) return '#f59e0b'; // Kuning/Oranye Gejala Awal
        return '#dc2626'; // Merah Parah
      });

      APP_STATE.severityChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: trend.map((t, i) => `Cek #${i + 1} (Umur ${t.hst} Hr)`),
          datasets: [
            {
              label: 'Tingkat Kerusakan Daun (%)',
              data: barValues,
              backgroundColor: barColors,
              borderRadius: 4,
              maxBarThickness: 34,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (item) => {
                  const realVal = Number(trend[item.dataIndex].severity_final || 0).toFixed(1);
                  const kat = realVal == 0 ? 'Sehat' : realVal <= 5.0 ? 'Gejala Awal' : 'Parah';
                  return `Kerusakan Daun: ${realVal}% (${kat})`;
                },
              },
            },
          },
          scales: {
            x: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { display: false } },
            y: {
              beginAtZero: true,
              ticks: { color: '#64748b', font: { size: 10 }, callback: (v) => v + '%' },
              grid: { color: '#f1f5f9' },
            },
          },
        },
      });
    }

    // 3. Kartu Arsip Pemeriksaan Ringkas & Manajemen Memori UNO Q
    const countBadge = document.getElementById('historyRecordCountBadge');
    if (countBadge) countBadge.textContent = `${records.length} Pemeriksaan`;

    APP_STATE.historyRecords = records;

    const gallery = document.getElementById('historyGalleryList');
    if (!gallery) return;
    gallery.innerHTML = '';

    if (records.length === 0) {
      gallery.innerHTML = `
        <div class="p-6 text-center bg-slate-50 border border-slate-200 rounded-lg text-slate-500 text-xs">
          Belum ada riwayat pemeriksaan tersimpan. Silakan lakukan inspeksi daun ganda pada menu <strong>Inspeksi</strong>.
        </div>
      `;
      return;
    }

    records.forEach((rec) => {
      const level = rec.decision_level || 'SAFE';
      const card = document.createElement('div');
      card.className = `decision-banner decision-${level} p-3.5 space-y-2.5`;

      // Badge status validasi
      let valBadgeHtml = '<span class="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200">Belum Divalidasi</span>';
      if (rec.validation_status === 'VALIDATED_ACCURATE') {
        valBadgeHtml = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">Tervalidasi (Akurat)</span>';
      } else if (rec.validation_status === 'VALIDATED_ADJUSTED') {
        valBadgeHtml = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-sky-100 text-sky-800 border border-sky-300">Tervalidasi (Disesuaikan)</span>';
      } else if (rec.validation_status === 'REJECTED_FALSE_POSITIVE') {
        valBadgeHtml = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-300">Ditolak (False Positive)</span>';
      }

      // Catatan validasi jika ada
      let noteHtml = '';
      if (rec.validation_notes) {
        noteHtml = `
          <div class="p-2 rounded bg-white/80 border border-emerald-200 text-[11px] text-slate-700 leading-relaxed">
            <span class="font-bold text-emerald-800">Catatan Validasi (${rec.validated_at ? formatWibTimestamp(rec.validated_at) : 'Tervalidasi'}):</span> ${rec.validation_notes}
          </div>
        `;
      }

      card.innerHTML = `
        <div class="flex items-start justify-between gap-2 border-b border-slate-100 pb-2">
          <div>
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="font-mono-num text-[10px] font-bold text-slate-500 bg-slate-100 px-1 py-0.5 rounded">#${rec.id}</span>
              <span class="status-pill-${level} px-1.5 py-0.5 rounded text-[10px] font-bold uppercase">${rec.decision_code}</span>
              <span class="text-xs font-bold text-slate-900">${rec.decision_title}</span>
              ${valBadgeHtml}
            </div>
            <div class="text-[11px] text-slate-500 mt-1">
              Waktu: <span class="font-mono-num font-medium text-slate-700">${formatWibTimestamp(rec.timestamp)}</span> • <strong>Umur ${rec.hst} Hari</strong> • Lembab Tanah ${Number(rec.soil_moisture).toFixed(0)}%
            </div>
          </div>
          <div class="text-right shrink-0">
            <div class="text-sm font-bold font-mono-num text-slate-900">${Number(rec.severity_final).toFixed(1)}%</div>
            <div class="text-[10px] text-slate-500">Kerusakan</div>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-2.5">
          <div>
            <div class="text-[10px] text-slate-600 font-medium mb-1">1. Daun Atas (${Number(rec.severity_top).toFixed(1)}%)</div>
            <img src="${rec.img_top_mask}" class="w-full h-24 object-cover rounded border border-slate-200 cursor-pointer hover:opacity-90 transition" loading="lazy" onclick="openInspectionDetailModal(${rec.id})" title="Klik untuk cek visual detail & validasi" />
          </div>
          <div>
            <div class="text-[10px] text-slate-600 font-medium mb-1">2. Daun Bawah (${Number(rec.severity_bottom).toFixed(1)}%)</div>
            <img src="${rec.img_bottom_mask}" class="w-full h-24 object-cover rounded border border-slate-200 cursor-pointer hover:opacity-90 transition" loading="lazy" onclick="openInspectionDetailModal(${rec.id})" title="Klik untuk cek visual detail & validasi" />
          </div>
        </div>

        <div class="bg-slate-50 p-2.5 rounded border border-slate-200/80 text-xs text-slate-700 leading-relaxed">
          <strong>Solusi:</strong> ${rec.recommendation}
        </div>

        ${noteHtml}

        <!-- Tombol Aksi Riwayat: Cek/Validasi & Hapus -->
        <div class="flex items-center justify-between gap-2 pt-1 border-t border-slate-100/80">
          <button onclick="confirmDeleteInspection(${rec.id})"
            class="px-2.5 py-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 border border-rose-300 text-rose-700 text-xs font-semibold flex items-center gap-1 transition"
            title="Hapus riwayat dan file foto untuk menghemat memori Arduino UNO Q">
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 6h18m-2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
            <span>Hapus Foto &amp; Data</span>
          </button>

          <button onclick="openInspectionDetailModal(${rec.id})"
            class="px-3 py-1.5 rounded-lg bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold flex items-center gap-1 transition shadow-xs">
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <span>Cek &amp; Validasi</span>
          </button>
        </div>
      `;
      gallery.appendChild(card);
    });
  } catch (err) {
    console.error('History load error:', err);
  }
}

/* ================= INSPECTION VALIDATION & DETAIL MODAL CONTROLLER ================= */
async function openInspectionDetailModal(inspectionId) {
  let rec = null;
  if (APP_STATE.historyRecords && APP_STATE.historyRecords.length > 0) {
    rec = APP_STATE.historyRecords.find((r) => r.id === inspectionId);
  }

  // Jika belum ada di memori, ambil langsung dari REST API
  if (!rec) {
    try {
      const res = await fetch(`/api/v1/history/${inspectionId}`);
      if (res.ok) {
        rec = await res.json();
      }
    } catch (err) {
      console.error('Failed to fetch inspection detail:', err);
    }
  }

  if (!rec) {
    showToast('Data pemeriksaan tidak ditemukan');
    return;
  }

  APP_STATE.activeInspectionDetail = rec;

  const modal = document.getElementById('inspectionValidationModal');
  const inputId = document.getElementById('valInputInspectionId');
  const badgeId = document.getElementById('valModalIdBadge');
  const subTitle = document.getElementById('valModalSubtitle');
  const codeBadge = document.getElementById('valModalCodeBadge');
  const titleEl = document.getElementById('valModalTitle');
  const sevFinalEl = document.getElementById('valModalSeverityFinal');
  const recEl = document.getElementById('valModalRecommendation');

  if (inputId) inputId.value = rec.id;
  if (badgeId) badgeId.textContent = `#${rec.id}`;
  if (subTitle) {
    subTitle.textContent = `${formatWibTimestamp(rec.timestamp)} • Umur ${rec.hst} Hari • Varietas: ${rec.variety}`;
  }
  if (codeBadge) {
    codeBadge.textContent = rec.decision_code || 'SAFE';
    codeBadge.className = `px-2 py-0.5 rounded text-xs font-bold uppercase status-pill-${rec.decision_level || 'SAFE'}`;
  }
  if (titleEl) titleEl.textContent = rec.decision_title || 'Pemeriksaan';
  if (sevFinalEl) sevFinalEl.textContent = `${Number(rec.severity_final).toFixed(1)}%`;
  if (recEl) recEl.textContent = rec.recommendation || '-';

  // Daun Atas
  const topOrig = document.getElementById('valModalTopOrig');
  const topMask = document.getElementById('valModalTopMask');
  const topSev = document.getElementById('valModalTopSev');
  const topGating = document.getElementById('valModalTopGating');
  if (topOrig) topOrig.src = rec.img_top_orig || '';
  if (topMask) topMask.src = rec.img_top_mask || '';
  if (topSev) topSev.textContent = `${Number(rec.severity_top).toFixed(1)}%`;
  if (topGating) {
    topGating.textContent = `Gating: ${rec.gating_top_class} (${(Number(rec.gating_top_conf) * 100).toFixed(0)}%)`;
  }

  // Daun Bawah
  const bottomOrig = document.getElementById('valModalBottomOrig');
  const bottomMask = document.getElementById('valModalBottomMask');
  const bottomSev = document.getElementById('valModalBottomSev');
  const bottomGating = document.getElementById('valModalBottomGating');
  if (bottomOrig) bottomOrig.src = rec.img_bottom_orig || '';
  if (bottomMask) bottomMask.src = rec.img_bottom_mask || '';
  if (bottomSev) bottomSev.textContent = `${Number(rec.severity_bottom).toFixed(1)}%`;
  if (bottomGating) {
    bottomGating.textContent = `Gating: ${rec.gating_bottom_class} (${(Number(rec.gating_bottom_conf) * 100).toFixed(0)}%)`;
  }

  // Sensor
  const tempEl = document.getElementById('valModalTemp');
  const humEl = document.getElementById('valModalHum');
  const soilEl = document.getElementById('valModalSoil');
  if (tempEl) tempEl.textContent = `${Number(rec.temperature).toFixed(1)} °C`;
  if (humEl) humEl.textContent = `${Number(rec.humidity).toFixed(0)} %`;
  if (soilEl) soilEl.textContent = `${Number(rec.soil_moisture).toFixed(0)} %`;

  // Status Validasi Saat Ini
  const currStatusBadge = document.getElementById('valModalCurrentStatusBadge');
  const selectStatus = document.getElementById('valInputStatus');
  const inputSevOverride = document.getElementById('valInputSeverityOverride');
  const valAtEl = document.getElementById('valModalValidatedAt');
  const inputNotes = document.getElementById('valInputNotes');

  const curStatus = rec.validation_status || 'PENDING';
  if (selectStatus) selectStatus.value = curStatus;
  if (currStatusBadge) {
    currStatusBadge.textContent = `Status: ${curStatus}`;
  }
  if (inputSevOverride) {
    inputSevOverride.value = (rec.severity_override !== null && rec.severity_override !== undefined)
      ? Number(rec.severity_override).toFixed(1)
      : Number(rec.severity_final).toFixed(1);
  }
  if (valAtEl) {
    valAtEl.textContent = rec.validated_at ? formatWibTimestamp(rec.validated_at) : 'Belum pernah divalidasi';
  }
  if (inputNotes) {
    inputNotes.value = rec.validation_notes || '';
  }

  if (modal) modal.classList.remove('hidden');
}

function closeInspectionValidationModal() {
  const modal = document.getElementById('inspectionValidationModal');
  if (modal) modal.classList.add('hidden');
  APP_STATE.activeInspectionDetail = null;
}

async function submitInspectionValidation(event) {
  if (event) event.preventDefault();
  const inputId = document.getElementById('valInputInspectionId');
  const selectStatus = document.getElementById('valInputStatus');
  const inputSevOverride = document.getElementById('valInputSeverityOverride');
  const inputNotes = document.getElementById('valInputNotes');

  if (!inputId || !inputId.value) {
    showToast('ID pemeriksaan tidak valid');
    return;
  }

  const inspectionId = parseInt(inputId.value, 10);
  const status = selectStatus ? selectStatus.value : 'PENDING';
  const notes = inputNotes ? inputNotes.value.trim() : '';
  let sevOverride = null;
  if (inputSevOverride && inputSevOverride.value !== '') {
    const parsed = parseFloat(inputSevOverride.value);
    if (!isNaN(parsed) && parsed >= 0 && parsed <= 100) {
      sevOverride = parsed;
    }
  }

  const payload = {
    validation_status: status,
    validation_notes: notes,
    severity_override: sevOverride,
  };

  const btnSave = document.getElementById('btnSaveValidation');
  if (btnSave) {
    btnSave.disabled = true;
    btnSave.textContent = 'Menyimpan...';
  }

  try {
    const res = await fetch(`/api/v1/history/${inspectionId}/validate`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      showToast(`Validasi pemeriksaan #${inspectionId} berhasil disimpan!`);
      closeInspectionValidationModal();
      await loadInspectionHistory();
    } else {
      const errData = await res.json().catch(() => ({}));
      showToast(`Gagal menyimpan validasi: ${errData.detail || 'Terjadi kesalahan'}`);
    }
  } catch (err) {
    console.error('Validation submit error:', err);
    showToast('Koneksi gagal saat menyimpan validasi');
  } finally {
    if (btnSave) {
      btnSave.disabled = false;
      btnSave.textContent = 'Simpan Validasi';
    }
  }
}

async function confirmDeleteInspection(inspectionId) {
  if (!confirm(`Hapus riwayat pemeriksaan #${inspectionId}?\n\nFile foto daun asli dan hasil mask pada memori internal Arduino UNO Q akan dihapus secara permanen guna menghemat ruang penyimpanan eMMC.`)) {
    return;
  }

  try {
    const res = await fetch(`/api/v1/history/${inspectionId}`, {
      method: 'DELETE',
    });

    if (res.ok) {
      const data = await res.json();
      showToast(`Pemeriksaan #${inspectionId} berhasil dihapus (${data.freed_kb || 0} KB memori UNO Q dibebaskan)!`);
      closeInspectionValidationModal();
      await loadInspectionHistory();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(`Gagal menghapus: ${err.detail || 'Terjadi kesalahan'}`);
    }
  } catch (err) {
    console.error('Delete inspection error:', err);
    showToast('Koneksi gagal saat menghapus riwayat pemeriksaan');
  }
}

function deleteInspectionFromModal() {
  const inputId = document.getElementById('valInputInspectionId');
  if (inputId && inputId.value) {
    confirmDeleteInspection(parseInt(inputId.value, 10));
  }
}

/* ================= SAVE PLANT SETTINGS & HARDWARE CONTROL ================= */
async function saveFarmSettings() {
  const plotName = document.getElementById('setPlotName').value;
  const plantingDate = document.getElementById('setPlantingDate').value;
  const variety = document.getElementById('setVariety').value;
  const manualHstRaw = document.getElementById('setManualHst').value;

  const payload = {
    plot_name: plotName,
    planting_date: plantingDate,
    variety: variety,
  };
  if (manualHstRaw === '' || manualHstRaw === null) {
    payload.clear_hst_override = true;
  } else {
    payload.manual_hst_override = parseInt(manualHstRaw, 10);
  }

  try {
    const res = await fetch('/api/v1/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    togglePlantSetupForm(false);
    showToast(`Patokan tanam disimpan: ${data.farm.variety} (Umur ${data.farm.active_hst} Hari)`);
    await loadStatusAndHeader();
  } catch (err) {
    console.error('Settings error:', err);
  }
}

async function clearManualHstOverride() {
  document.getElementById('setManualHst').value = '';
  await saveFarmSettings();
}

async function testLedRing(state) {
  const pwm = parseInt(document.getElementById('sliderLedPwm').value || '220', 10);
  try {
    const res = await fetch('/api/v1/hardware/led-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state, pwm }),
    });
    const data = await res.json();
    if (state) {
      showToast(`Lampu LED Kamera menyala (Kecerahan ${data.led_bridge.pwm}/255)`);
    } else {
      showToast('Lampu LED Kamera dimatikan');
    }
  } catch (err) {
    console.error('LED test error:', err);
  }
}

/* ================= 6-DIGIT PIN AUTHENTICATION GATEWAY ================= */
const PIN_STATE = {
  entered: '',
  isSubmitting: false,
  targetPin: '123456',
};

function isSystemUnlocked() {
  return document.documentElement.classList.contains('pin-unlocked');
}

function updatePinSlotsUI() {
  for (let i = 0; i < 6; i++) {
    const slot = document.getElementById(`pinSlot${i}`);
    if (!slot) continue;
    slot.classList.remove('filled', 'active', 'error', 'success');
    if (i < PIN_STATE.entered.length) {
      slot.classList.add('filled');
    } else if (i === PIN_STATE.entered.length) {
      slot.classList.add('active');
    }
  }
}

function clearPinAlert() {
  const alertBox = document.getElementById('pinAlertBox');
  const successBox = document.getElementById('pinSuccessBox');
  if (alertBox) alertBox.classList.add('hidden');
  if (successBox) successBox.classList.add('hidden');
  for (let i = 0; i < 6; i++) {
    const slot = document.getElementById(`pinSlot${i}`);
    if (slot) slot.classList.remove('error', 'success');
  }
}

function handlePinNumpad(digit) {
  if (PIN_STATE.isSubmitting || isSystemUnlocked()) return;
  if (PIN_STATE.entered.length >= 6) return;
  
  clearPinAlert();
  PIN_STATE.entered += String(digit);
  updatePinSlotsUI();

  if (PIN_STATE.entered.length === 6) {
    verifyEnteredPin();
  }
}

function handlePinBackspace() {
  if (PIN_STATE.isSubmitting || isSystemUnlocked()) return;
  if (PIN_STATE.entered.length === 0) return;
  
  clearPinAlert();
  PIN_STATE.entered = PIN_STATE.entered.slice(0, -1);
  updatePinSlotsUI();
}

function handlePinClear() {
  if (PIN_STATE.isSubmitting || isSystemUnlocked()) return;
  clearPinAlert();
  PIN_STATE.entered = '';
  updatePinSlotsUI();
}

async function verifyEnteredPin() {
  if (PIN_STATE.entered.length !== 6 || PIN_STATE.isSubmitting) return;
  PIN_STATE.isSubmitting = true;

  const alertBox = document.getElementById('pinAlertBox');
  const alertText = document.getElementById('pinAlertText');
  const successBox = document.getElementById('pinSuccessBox');
  const slotsContainer = document.getElementById('pinSlotsContainer');

  let isValid = false;

  try {
    const res = await fetch('/api/v1/auth/verify-pin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: PIN_STATE.entered }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.valid) isValid = true;
    }
  } catch (netErr) {
    // Offline resilience: Verifikasi mandiri di client jika koneksi backend lambat
    if (PIN_STATE.entered === PIN_STATE.targetPin) {
      isValid = true;
    }
  }

  if (isValid) {
    // Tanda Sukses
    for (let i = 0; i < 6; i++) {
      const slot = document.getElementById(`pinSlot${i}`);
      if (slot) slot.classList.add('success');
    }
    if (successBox) successBox.classList.remove('hidden');

    try {
      sessionStorage.setItem('ipomoea_pin_auth', 'granted');
    } catch (e) {}

    setTimeout(() => {
      document.documentElement.classList.add('pin-unlocked');
      const overlay = document.getElementById('pinAuthOverlay');
      if (overlay) {
        overlay.classList.add('opacity-0', 'pointer-events-none');
        setTimeout(() => {
          overlay.style.display = 'none';
        }, 300);
      }
      PIN_STATE.entered = '';
      PIN_STATE.isSubmitting = false;
      showToast('Akses Terverifikasi. Selamat datang di Ipomoea Edge-AIoT.');
    }, 450);
  } else {
    // Tanda Peringatan / Salah
    if (navigator.vibrate) {
      navigator.vibrate([100, 50, 100]);
    }
    for (let i = 0; i < 6; i++) {
      const slot = document.getElementById(`pinSlot${i}`);
      if (slot) slot.classList.add('error');
    }
    if (slotsContainer) {
      slotsContainer.classList.add('pin-shake');
      setTimeout(() => slotsContainer.classList.remove('pin-shake'), 450);
    }
    if (alertBox) {
      if (alertText) alertText.textContent = 'PIN Akses Salah! Kombinasi 6 angka tidak cocok.';
      alertBox.classList.remove('hidden');
    }

    setTimeout(() => {
      PIN_STATE.entered = '';
      PIN_STATE.isSubmitting = false;
      updatePinSlotsUI();
    }, 850);
  }
}

function lockSystem() {
  try {
    sessionStorage.removeItem('ipomoea_pin_auth');
  } catch (e) {}

  document.documentElement.classList.remove('pin-unlocked');
  const overlay = document.getElementById('pinAuthOverlay');
  if (overlay) {
    overlay.style.display = 'flex';
    overlay.classList.remove('opacity-0', 'pointer-events-none', 'hidden');
  }
  PIN_STATE.entered = '';
  PIN_STATE.isSubmitting = false;
  clearPinAlert();
  updatePinSlotsUI();
  showToast('Sistem telah dikunci. Masukkan PIN untuk mengakses kembali.');
}

// Global Keyboard Listener untuk Mengetik Menggunakan Keyboard Laptop / PC
window.addEventListener('keydown', (e) => {
  if (isSystemUnlocked()) return;

  if (e.key >= '0' && e.key <= '9') {
    e.preventDefault();
    handlePinNumpad(e.key);
  } else if (e.key === 'Backspace') {
    e.preventDefault();
    handlePinBackspace();
  } else if (e.key === 'Escape' || e.key === 'Delete') {
    e.preventDefault();
    handlePinClear();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (PIN_STATE.entered.length === 6) {
      verifyEnteredPin();
    }
  }
});

/* ================= INITIALIZE ON PAGE LOAD ================= */
window.addEventListener('DOMContentLoaded', async () => {
  // 0. Cek otentikasi PIN
  if (sessionStorage.getItem('ipomoea_pin_auth') === 'granted') {
    document.documentElement.classList.add('pin-unlocked');
    const overlay = document.getElementById('pinAuthOverlay');
    if (overlay) overlay.style.display = 'none';
  } else {
    document.documentElement.classList.remove('pin-unlocked');
    updatePinSlotsUI();
  }

  // 1. Mulai jam real-time Kota Tangerang (WIB / UTC+7) berdetak setiap detik
  updateTangerangLiveClock();
  setInterval(updateTangerangLiveClock, 1000);

  // 2. Muat status kebun & header
  await loadStatusAndHeader();
  APP_STATE.capturePhase = 'TOP_STANDBY';
  renderSingleCameraUI();

  // 3. Pra-muat data sensor di latar belakang agar tabel langsung terisi saat tab dibuka
  loadTelemetryAndChart();

  // 4. Sinkronisasi Real-Time otomatis setiap 3 detik dari sensor ESP32
  setInterval(() => {
    loadStatusAndHeader();
    if (APP_STATE.activeTab === 'tab-land') {
      loadTelemetryAndChart();
    }
  }, 3000);
});
