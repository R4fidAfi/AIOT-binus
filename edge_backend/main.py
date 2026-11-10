"""
FastAPI Unified Edge Server for Arduino UNO Q (Qualcomm Dragonwing QRB2210 - Debian Linux).
Serves the Mobile-First Web Application (/web_app) and REST API (/api/v1/*).
"""

import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .ai_inference import vision_pipeline
from .camera_service import (
    CAPTURE_DIR,
    capture_leaf_surface,
    rig_bridge,
    webcam_controller,
)
from .database import (
    get_farm_settings,
    get_inspection_history,
    get_latest_telemetry,
    get_recent_telemetry_window,
    get_telemetry_history,
    init_db,
    insert_inspection,
    insert_telemetry,
    update_farm_settings,
)
from .decision_engine import (
    detect_post_rain_heat_spike,
    evaluate_multimodal_decision,
    get_hst_phase_info,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
WEB_APP_DIR = os.path.join(PROJECT_ROOT, "web_app")

os.makedirs(CAPTURE_DIR, exist_ok=True)
os.makedirs(WEB_APP_DIR, exist_ok=True)

app = FastAPI(
    title="Edge-AIoT Kangkung Dual-Surface Vision & Microclimate Server",
    description="5-Stage High-Precision Computer Vision & Multimodal Decision Support on Arduino UNO Q",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directories
app.mount("/captures", StaticFiles(directory=CAPTURE_DIR), name="captures")
app.mount("/static", StaticFiles(directory=WEB_APP_DIR), name="static")

# Active dual-capture session state in memory (for pairing Top + Bottom before AI analysis)
CURRENT_SESSION: Dict[str, Any] = {
    "top_abs_path": None,
    "top_url": None,
    "top_meta": None,
    "bottom_abs_path": None,
    "bottom_url": None,
    "bottom_meta": None,
    "last_updated": None,
}


class TelemetryPayload(BaseModel):
    temperature: float
    humidity: float
    soil_moisture: float
    adc_raw: Optional[int] = 1950
    node_id: Optional[str] = "ESP32-FIELD-01"


class AnalyzeDualPayload(BaseModel):
    hst_override: Optional[int] = None
    variety_override: Optional[str] = None


class SettingsUpdatePayload(BaseModel):
    planting_date: Optional[str] = None
    manual_hst_override: Optional[int] = None
    clear_hst_override: Optional[bool] = False
    variety: Optional[str] = None
    plot_name: Optional[str] = None
    demo_scenario: Optional[str] = None
    led_brightness_pwm: Optional[int] = None


class DemoPresetPayload(BaseModel):
    preset: str  # PETAK_1_SEHAT, PETAK_2_STRES_AIR, PETAK_3_BRONTOK_PANEN, CUACA_BRONTOK, INFEKSI_DINI


class LedTestPayload(BaseModel):
    state: bool
    pwm: Optional[int] = 225


class CameraControlPayload(BaseModel):
    side: Optional[str] = "top"


def seed_initial_inspections_if_empty() -> None:
    """
    Generate 3 historical dual-surface inspections on first boot so Menu 3 (Riwayat & Tren)
    immediately displays realistic images, masks, and disease progression (<24h spread).
    """
    existing = get_inspection_history(limit=5)
    if len(existing) > 0:
        return

    now = datetime.now()
    seed_scenarios = [
        {
            "hours_ago": 28,
            "hst": 15,
            "variety": "Kangkung Daun Lebar",
            "scenario": "PETAK_1_SEHAT",
            "temp": 28.4,
            "rh": 72.0,
            "soil": 64.5,
            "spike": 0,
        },
        {
            "hours_ago": 18,
            "hst": 15,
            "variety": "Kangkung Daun Lebar",
            "scenario": "PETAK_2_STRES_AIR",
            "temp": 31.8,
            "rh": 64.0,
            "soil": 28.5,
            "spike": 0,
        },
        {
            "hours_ago": 9,
            "hst": 16,
            "variety": "Kangkung Daun Lebar",
            "scenario": "INFEKSI_DINI",
            "temp": 29.5,
            "rh": 83.0,
            "soil": 61.0,
            "spike": 1,
        },
        {
            "hours_ago": 1,
            "hst": 16,
            "variety": "Kangkung Daun Lebar",
            "scenario": "PETAK_3_BRONTOK_PANEN",
            "temp": 30.8,
            "rh": 79.5,
            "soil": 62.4,
            "spike": 1,
        },
    ]

    for item in seed_scenarios:
        top_abs, top_url, _ = capture_leaf_surface(
            side="top",
            variety=item["variety"],
            scenario=item["scenario"],
            hst=item["hst"],
            soil_moisture=item["soil"],
            prefer_simulation=True,
        )
        bot_abs, bot_url, _ = capture_leaf_surface(
            side="bottom",
            variety=item["variety"],
            scenario=item["scenario"],
            hst=item["hst"],
            soil_moisture=item["soil"],
            prefer_simulation=True,
        )
        ai_res = vision_pipeline.analyze_dual_surface(top_abs, bot_abs)
        dec = evaluate_multimodal_decision(
            severity_top=ai_res["severity_top"],
            severity_bottom=ai_res["severity_bottom"],
            severity_final=ai_res["severity_final"],
            pathogen_detected=ai_res["pathogen_detected"],
            hst=item["hst"],
            variety=item["variety"],
            temperature=item["temp"],
            humidity=item["rh"],
            soil_moisture=item["soil"],
            post_rain_heat_spike=bool(item["spike"]),
        )
        ts_str = (now - timedelta(hours=item["hours_ago"])).strftime("%Y-%m-%d %H:%M:%S")
        insert_inspection(
            {
                "timestamp": ts_str,
                "hst": item["hst"],
                "variety": item["variety"],
                "img_top_orig": top_url,
                "img_top_mask": ai_res["top"]["mask_url"],
                "img_top_stage": ai_res["top"]["stage_url"],
                "img_bottom_orig": bot_url,
                "img_bottom_mask": ai_res["bottom"]["mask_url"],
                "img_bottom_stage": ai_res["bottom"]["stage_url"],
                "gating_top_class": ai_res["top"]["gating_class"],
                "gating_top_conf": ai_res["top"]["gating_conf"],
                "gating_bottom_class": ai_res["bottom"]["gating_class"],
                "gating_bottom_conf": ai_res["bottom"]["gating_conf"],
                "severity_top": ai_res["severity_top"],
                "severity_bottom": ai_res["severity_bottom"],
                "severity_final": ai_res["severity_final"],
                "severity_category": dec["severity_category"],
                "pathogen_detected": ai_res["pathogen_detected"],
                "latency_ms": ai_res["latency_ms"],
                "temperature": item["temp"],
                "humidity": item["rh"],
                "soil_moisture": item["soil"],
                "post_rain_heat_spike": item["spike"],
                "decision_code": dec["decision_code"],
                "decision_title": dec["decision_title"],
                "decision_level": dec["decision_level"],
                "recommendation": dec["recommendation"],
                "action_steps": dec["action_steps"],
                "pipeline_metrics": {
                    "asymmetry_analysis": ai_res["asymmetry_analysis"],
                    "economic_impact": dec["economic_impact"],
                    "top_timing": ai_res["top"]["timing_ms"],
                    "bottom_timing": ai_res["bottom"]["timing_ms"],
                },
            }
        )


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    seed_initial_inspections_if_empty()


@app.get("/", include_in_schema=False)
def serve_web_app() -> FileResponse:
    index_file = os.path.join(WEB_APP_DIR, "index.html")
    return FileResponse(index_file)


@app.get("/api/v1/status")
def api_get_status() -> Dict[str, Any]:
    settings = get_farm_settings()
    telemetry = get_latest_telemetry()
    recent_window = get_recent_telemetry_window(hours=6)
    spike_info = detect_post_rain_heat_spike(
        current_temp=telemetry["temperature"],
        current_rh=telemetry["humidity"],
        recent_window=recent_window,
    )
    hst_info = get_hst_phase_info(settings["active_hst"])

    return {
        "status": "OK",
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "farm": settings,
        "hst_info": hst_info,
        "telemetry": telemetry,
        "weather_radar": spike_info,
        "capture_session": {
            "top_ready": CURRENT_SESSION["top_url"] is not None,
            "top_url": CURRENT_SESSION["top_url"],
            "top_meta": CURRENT_SESSION["top_meta"],
            "bottom_ready": CURRENT_SESSION["bottom_url"] is not None,
            "bottom_url": CURRENT_SESSION["bottom_url"],
            "bottom_meta": CURRENT_SESSION["bottom_meta"],
        },
        "hardware": {
            "mpu": "Qualcomm Dragonwing QRB2210 (Debian Linux - FastAPI Unified)",
            "mcu": "STM32U585 (LED Ring Pin D3 PWM + Trigger Button Pin D2)",
            "ram_footprint_est_mb": 640,
            "led_ring_state": rig_bridge.led_on,
            "led_pwm": settings["led_brightness_pwm"],
            "esp32_node": telemetry.get("node_id", "ESP32-FIELD-01"),
            "esp32_last_seen": settings.get("esp32_last_seen") or telemetry["timestamp"],
            "flip_stage": "Matte-Black In-Situ Flip-Stage (20 cm Working Distance)",
        },
    }


@app.post("/api/v1/telemetry")
def api_post_telemetry(payload: TelemetryPayload) -> Dict[str, Any]:
    recent_window = get_recent_telemetry_window(hours=6)
    spike_info = detect_post_rain_heat_spike(
        current_temp=payload.temperature,
        current_rh=payload.humidity,
        recent_window=recent_window,
    )
    saved = insert_telemetry(
        temperature=payload.temperature,
        humidity=payload.humidity,
        soil_moisture=payload.soil_moisture,
        adc_raw=payload.adc_raw or 1950,
        node_id=payload.node_id or "ESP32-FIELD-01",
        post_rain_heat_spike=1 if spike_info["is_spike"] else 0,
    )
    return {"status": "SAVED", "telemetry": saved, "weather_radar": spike_info}


@app.get("/api/v1/telemetry/history")
def api_get_telemetry_history(limit: int = 24) -> Dict[str, Any]:
    history = get_telemetry_history(limit=limit)
    latest = get_latest_telemetry()
    recent_window = get_recent_telemetry_window(hours=6)
    spike_info = detect_post_rain_heat_spike(
        current_temp=latest["temperature"],
        current_rh=latest["humidity"],
        recent_window=recent_window,
    )
    settings = get_farm_settings()
    return {
        "latest": latest,
        "history": history,
        "weather_radar": spike_info,
        "hst_info": get_hst_phase_info(settings["active_hst"]),
    }


@app.post("/api/v1/camera/start")
def api_start_live_webcam(payload: Optional[CameraControlPayload] = None) -> Dict[str, Any]:
    """
    Triggered when user clicks 'Nyalakan Kamera'.
    Opens the USB Webcam on Arduino UNO Q (640x480 @ 10 FPS) and turns ON the LED Ring (Pin D3).
    """
    side = payload.side if (payload and payload.side) else "top"
    info = webcam_controller.start_camera(side=side)
    return {"status": "CAMERA_ON", "camera": info}


@app.post("/api/v1/camera/stop")
def api_stop_live_webcam() -> Dict[str, Any]:
    """
    Immediately stops the live stream, releases the USB Webcam from RAM/CPU, and turns OFF the LED Ring.
    """
    info = webcam_controller.stop_camera()
    return {"status": "CAMERA_OFF", "camera": info}


@app.get("/api/v1/camera/stream")
def api_stream_live_webcam(side: str = "top") -> StreamingResponse:
    """
    Streams lightweight 10-FPS MJPEG frames from the USB Webcam while active.
    Automatically stops when the user clicks 'Ambil Foto' or 'Matikan Kamera'.
    """
    settings = get_farm_settings()
    telemetry = get_latest_telemetry()
    side_norm = "top" if side.lower() not in ("bottom", "bawah", "abaxial") else "bottom"

    return StreamingResponse(
        webcam_controller.stream_mjpeg_generator(
            side=side_norm,
            variety=settings["variety"],
            scenario=settings["demo_scenario"],
            hst=int(settings["active_hst"]),
            soil_moisture=float(telemetry["soil_moisture"]),
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.post("/api/v1/capture/{side}")
async def api_capture_leaf_side(
    side: str,
    scenario_override: Optional[str] = Form(None),
    variety_override: Optional[str] = Form(None),
    hst_override: Optional[int] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    """
    Step 1 or Step 2 of Dual-Surface Leaf Acquisition:
    Captures either 'top' (Adaxial) or 'bottom' (Abaxial) leaf image and returns the preview URL
    immediately so the mobile Web App displays the photo before starting the 5-stage AI scan animation.
    """
    side_norm = "top" if side.lower() not in ("bottom", "bawah", "abaxial") else "bottom"
    settings = get_farm_settings()
    telemetry = get_latest_telemetry()

    active_variety = variety_override or settings["variety"]
    active_hst = int(hst_override) if hst_override is not None else int(settings["active_hst"])
    active_scenario = scenario_override or settings["demo_scenario"]

    uploaded_bytes = None
    if file is not None:
        uploaded_bytes = await file.read()

    abs_path, url_path, meta = capture_leaf_surface(
        side=side_norm,
        variety=active_variety,
        scenario=active_scenario,
        hst=active_hst,
        soil_moisture=float(telemetry["soil_moisture"]),
        uploaded_bytes=uploaded_bytes,
    )

    if side_norm == "top":
        CURRENT_SESSION["top_abs_path"] = abs_path
        CURRENT_SESSION["top_url"] = url_path
        CURRENT_SESSION["top_meta"] = meta
    else:
        CURRENT_SESSION["bottom_abs_path"] = abs_path
        CURRENT_SESSION["bottom_url"] = url_path
        CURRENT_SESSION["bottom_meta"] = meta

    CURRENT_SESSION["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "status": "CAPTURED",
        "side": side_norm,
        "image_url": url_path,
        "meta": meta,
        "both_ready": bool(
            CURRENT_SESSION["top_abs_path"] and CURRENT_SESSION["bottom_abs_path"]
        ),
        "session": {
            "top_url": CURRENT_SESSION["top_url"],
            "bottom_url": CURRENT_SESSION["bottom_url"],
        },
    }


@app.post("/api/v1/capture/reset")
def api_reset_capture_session() -> Dict[str, Any]:
    webcam_controller.stop_camera()
    CURRENT_SESSION["top_abs_path"] = None
    CURRENT_SESSION["top_url"] = None
    CURRENT_SESSION["top_meta"] = None
    CURRENT_SESSION["bottom_abs_path"] = None
    CURRENT_SESSION["bottom_url"] = None
    CURRENT_SESSION["bottom_meta"] = None
    rig_bridge.last_trigger_step = 0
    return {"status": "RESET"}


@app.post("/api/v1/analyze-dual")
def api_analyze_dual_surface(payload: Optional[AnalyzeDualPayload] = None) -> Dict[str, Any]:
    """
    Executes the 5-Stage High-Precision Computer Vision Pipeline on the captured Top (Adaxial)
    and Bottom (Abaxial) leaf images, fuses with microclimate + topsoil moisture + HST,
    saves to SQLite, and returns the complete diagnosis.
    """
    # Ensure camera is 100% OFF before starting 5-stage AI inference
    webcam_controller.stop_camera()
    settings = get_farm_settings()
    telemetry = get_latest_telemetry()
    recent_window = get_recent_telemetry_window(hours=6)

    hst = (
        int(payload.hst_override)
        if (payload and payload.hst_override is not None)
        else int(settings["active_hst"])
    )
    variety = (
        payload.variety_override
        if (payload and payload.variety_override)
        else settings["variety"]
    )

    # If either side wasn't captured yet, auto-capture it so the user never gets stuck
    if not CURRENT_SESSION["top_abs_path"] or not os.path.exists(
        str(CURRENT_SESSION["top_abs_path"])
    ):
        top_abs, top_url, top_meta = capture_leaf_surface(
            side="top",
            variety=variety,
            scenario=settings["demo_scenario"],
            hst=hst,
            soil_moisture=float(telemetry["soil_moisture"]),
        )
        CURRENT_SESSION["top_abs_path"] = top_abs
        CURRENT_SESSION["top_url"] = top_url
        CURRENT_SESSION["top_meta"] = top_meta

    if not CURRENT_SESSION["bottom_abs_path"] or not os.path.exists(
        str(CURRENT_SESSION["bottom_abs_path"])
    ):
        bot_abs, bot_url, bot_meta = capture_leaf_surface(
            side="bottom",
            variety=variety,
            scenario=settings["demo_scenario"],
            hst=hst,
            soil_moisture=float(telemetry["soil_moisture"]),
        )
        CURRENT_SESSION["bottom_abs_path"] = bot_abs
        CURRENT_SESSION["bottom_url"] = bot_url
        CURRENT_SESSION["bottom_meta"] = bot_meta

    ai_res = vision_pipeline.analyze_dual_surface(
        CURRENT_SESSION["top_abs_path"], CURRENT_SESSION["bottom_abs_path"]
    )

    spike_info = detect_post_rain_heat_spike(
        current_temp=float(telemetry["temperature"]),
        current_rh=float(telemetry["humidity"]),
        recent_window=recent_window,
    )

    decision = evaluate_multimodal_decision(
        severity_top=ai_res["severity_top"],
        severity_bottom=ai_res["severity_bottom"],
        severity_final=ai_res["severity_final"],
        pathogen_detected=ai_res["pathogen_detected"],
        hst=hst,
        variety=variety,
        temperature=float(telemetry["temperature"]),
        humidity=float(telemetry["humidity"]),
        soil_moisture=float(telemetry["soil_moisture"]),
        post_rain_heat_spike=bool(spike_info["is_spike"]),
    )

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pipeline_metrics = {
        "asymmetry_analysis": ai_res["asymmetry_analysis"],
        "economic_impact": decision["economic_impact"],
        "pipeline_summary": ai_res["pipeline_summary"],
        "top_details": {
            "total_leaf_px": ai_res["top"]["total_leaf_px"],
            "lesion_px": ai_res["top"]["lesion_px"],
            "removed_speckles": ai_res["top"]["removed_speckles"],
            "removed_shadows": ai_res["top"]["removed_shadows"],
            "tta_applied": ai_res["top"]["tta_applied"],
            "timing_ms": ai_res["top"]["timing_ms"],
        },
        "bottom_details": {
            "total_leaf_px": ai_res["bottom"]["total_leaf_px"],
            "lesion_px": ai_res["bottom"]["lesion_px"],
            "white_pustule_px": ai_res["bottom"]["white_pustule_px"],
            "removed_speckles": ai_res["bottom"]["removed_speckles"],
            "removed_shadows": ai_res["bottom"]["removed_shadows"],
            "tta_applied": ai_res["bottom"]["tta_applied"],
            "timing_ms": ai_res["bottom"]["timing_ms"],
        },
    }

    record = {
        "timestamp": now_str,
        "hst": hst,
        "variety": variety,
        "img_top_orig": CURRENT_SESSION["top_url"],
        "img_top_mask": ai_res["top"]["mask_url"],
        "img_top_stage": ai_res["top"]["stage_url"],
        "img_bottom_orig": CURRENT_SESSION["bottom_url"],
        "img_bottom_mask": ai_res["bottom"]["mask_url"],
        "img_bottom_stage": ai_res["bottom"]["stage_url"],
        "gating_top_class": ai_res["top"]["gating_class"],
        "gating_top_conf": ai_res["top"]["gating_conf"],
        "gating_bottom_class": ai_res["bottom"]["gating_class"],
        "gating_bottom_conf": ai_res["bottom"]["gating_conf"],
        "severity_top": ai_res["severity_top"],
        "severity_bottom": ai_res["severity_bottom"],
        "severity_final": ai_res["severity_final"],
        "severity_category": decision["severity_category"],
        "pathogen_detected": ai_res["pathogen_detected"],
        "latency_ms": ai_res["latency_ms"],
        "temperature": float(telemetry["temperature"]),
        "humidity": float(telemetry["humidity"]),
        "soil_moisture": float(telemetry["soil_moisture"]),
        "post_rain_heat_spike": 1 if spike_info["is_spike"] else 0,
        "decision_code": decision["decision_code"],
        "decision_title": decision["decision_title"],
        "decision_level": decision["decision_level"],
        "recommendation": decision["recommendation"],
        "action_steps": decision["action_steps"],
        "pipeline_metrics": pipeline_metrics,
    }

    row_id = insert_inspection(record)
    record["id"] = row_id
    record["hst_info"] = get_hst_phase_info(hst)
    record["weather_radar"] = spike_info
    return record


@app.get("/api/v1/history")
def api_get_inspection_history(limit: int = 20) -> Dict[str, Any]:
    records = get_inspection_history(limit=limit)
    # Build chronological trend points for Chart.js
    trend = [
        {
            "id": r["id"],
            "timestamp": r["timestamp"][5:16],
            "hst": r["hst"],
            "severity_top": r["severity_top"],
            "severity_bottom": r["severity_bottom"],
            "severity_final": r["severity_final"],
            "decision_code": r["decision_code"],
            "soil_moisture": r["soil_moisture"],
        }
        for r in reversed(records)
    ]
    return {"count": len(records), "records": records, "trend": trend}


@app.post("/api/v1/settings")
def api_update_settings(payload: SettingsUpdatePayload) -> Dict[str, Any]:
    updated = update_farm_settings(
        planting_date=payload.planting_date,
        manual_hst_override=payload.manual_hst_override,
        clear_hst_override=bool(payload.clear_hst_override),
        variety=payload.variety,
        plot_name=payload.plot_name,
        demo_scenario=payload.demo_scenario,
        led_brightness_pwm=payload.led_brightness_pwm,
    )
    return {
        "status": "UPDATED",
        "farm": updated,
        "hst_info": get_hst_phase_info(updated["active_hst"]),
    }


@app.post("/api/v1/demo-preset")
def api_apply_judge_demo_preset(payload: DemoPresetPayload) -> Dict[str, Any]:
    """
    One-click Judge Pitching Scenario Switcher (3-in-1 Modular Demo Tray + Weather Spike).
    Updates sensor telemetry, HST, and active leaf simulation preset, and clears current capture buffer
    so the next inspection immediately demonstrates the chosen scenario.
    """
    preset = payload.preset.upper()
    api_reset_capture_session()

    if preset == "PETAK_1_SEHAT":
        update_farm_settings(manual_hst_override=12, demo_scenario="PETAK_1_SEHAT")
        tel = insert_telemetry(temperature=28.5, humidity=71.0, soil_moisture=64.0, adc_raw=1820)
        desc = "Petak 1: Kangkung Sehat Ideal (Umur 12 Hari, Lembab Tanah 64%, Daun Bersih 0%)"
    elif preset == "PETAK_2_STRES_AIR":
        update_farm_settings(manual_hst_override=11, demo_scenario="PETAK_2_STRES_AIR")
        tel = insert_telemetry(temperature=32.4, humidity=58.0, soil_moisture=26.5, adc_raw=2890)
        desc = "Petak 2: Tanah Lapisan Atas Kering (Lembab Tanah 26.5%, Suhu 32.4°C -> Jangan Semprot Pestisida!)"
    elif preset == "CUACA_BRONTOK":
        update_farm_settings(manual_hst_override=10, demo_scenario="CUACA_BRONTOK")
        # Insert high humidity history point then sudden heat spike
        insert_telemetry(temperature=24.5, humidity=91.5, soil_moisture=68.0, adc_raw=1740)
        tel = insert_telemetry(
            temperature=31.6, humidity=69.0, soil_moisture=65.0, adc_raw=1800, post_rain_heat_spike=1
        )
        desc = "Simulasi Cuaca 'Habis Hujan Langsung Panas' (RH 91.5% -> Suhu 31.6°C, Waspada Jamur Brontok)"
    elif preset == "INFEKSI_DINI":
        update_farm_settings(manual_hst_override=10, demo_scenario="INFEKSI_DINI")
        tel = insert_telemetry(temperature=29.2, humidity=84.0, soil_moisture=61.0, adc_raw=1910)
        desc = "Simulasi Gejala Awal (Umur 10 Hari, Kerusakan Ringan ~1.8% -> Perawatan Terarah)"
    else:  # PETAK_3_BRONTOK_PANEN
        update_farm_settings(manual_hst_override=17, demo_scenario="PETAK_3_BRONTOK_PANEN")
        tel = insert_telemetry(
            temperature=30.8, humidity=82.5, soil_moisture=63.0, adc_raw=1860, post_rain_heat_spike=1
        )
        desc = "Petak 3: Penyakit Brontok di Usia Panen (Umur 17 Hari, Bintil Putih >13% -> PANEN DINI SEKARANG!)"

    return {
        "status": "PRESET_APPLIED",
        "preset": preset,
        "description": desc,
        "telemetry": tel,
        "farm": get_farm_settings(),
    }


@app.post("/api/v1/hardware/led-test")
def api_hardware_led_test(payload: LedTestPayload) -> Dict[str, Any]:
    res = rig_bridge.set_led_ring(payload.state, pwm=payload.pwm or 225)
    return {"status": "OK", "led_bridge": res}
