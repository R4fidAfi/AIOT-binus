"""
SQLite3 Database Schema & Data Access Layer for Edge-AIoT Kangkung System.
Designed for lightweight operation on Arduino UNO Q (Qualcomm Dragonwing QRB2210).
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "edge_kangkung.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize SQLite tables and populate realistic initial data if empty."""
    conn = get_connection()
    cur = conn.cursor()

    # 1. Telemetry Table (ESP32 Field Node: DHT22 + Capacitive Soil Moisture Topsoil 3-5 cm)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL,
            soil_moisture REAL NOT NULL,
            adc_raw INTEGER DEFAULT 2150,
            node_id TEXT DEFAULT 'ESP32-FIELD-01',
            post_rain_heat_spike INTEGER DEFAULT 0
        )
        """
    )

    # 2. Dual-Surface Inspections Table (Top/Adaxial + Bottom/Abaxial + 5-Stage CV + Decision)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            hst INTEGER NOT NULL,
            variety TEXT NOT NULL,
            img_top_orig TEXT NOT NULL,
            img_top_mask TEXT NOT NULL,
            img_top_stage TEXT DEFAULT '',
            img_bottom_orig TEXT NOT NULL,
            img_bottom_mask TEXT NOT NULL,
            img_bottom_stage TEXT DEFAULT '',
            gating_top_class TEXT NOT NULL,
            gating_top_conf REAL NOT NULL,
            gating_bottom_class TEXT NOT NULL,
            gating_bottom_conf REAL NOT NULL,
            severity_top REAL NOT NULL,
            severity_bottom REAL NOT NULL,
            severity_final REAL NOT NULL,
            severity_category TEXT NOT NULL,
            pathogen_detected TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL,
            soil_moisture REAL NOT NULL,
            post_rain_heat_spike INTEGER DEFAULT 0,
            decision_code TEXT NOT NULL,
            decision_title TEXT NOT NULL,
            decision_level TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            action_steps_json TEXT NOT NULL,
            pipeline_metrics_json TEXT DEFAULT '{}'
        )
        """
    )

    # 3. Farm & Hardware Settings Table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS farm_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            planting_date TEXT NOT NULL,
            manual_hst_override INTEGER DEFAULT NULL,
            variety TEXT NOT NULL DEFAULT 'Kangkung Daun Lebar',
            plot_name TEXT NOT NULL DEFAULT 'Petak Sampel Utama (Bedeng A1)',
            demo_scenario TEXT NOT NULL DEFAULT 'AUTO',
            led_brightness_pwm INTEGER NOT NULL DEFAULT 220,
            esp32_last_seen TEXT DEFAULT NULL
        )
        """
    )

    # Ensure default farm_settings row exists (default 16 HST ago so judge demo is ready)
    cur.execute("SELECT COUNT(*) as cnt FROM farm_settings")
    if cur.fetchone()["cnt"] == 0:
        default_planting = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            INSERT INTO farm_settings (
                id, planting_date, manual_hst_override, variety, plot_name,
                demo_scenario, led_brightness_pwm, esp32_last_seen
            ) VALUES (1, ?, NULL, 'Kangkung Daun Lebar', 'Petak Sampel Utama (Bedeng A1)', 'AUTO', 220, ?)
            """,
            (default_planting, now_iso),
        )

    # Seed initial 12-hour microclimate telemetry if empty
    cur.execute("SELECT COUNT(*) as cnt FROM telemetry")
    if cur.fetchone()["cnt"] == 0:
        now = datetime.now()
        # Simulate night high RH -> morning transition -> current stable daytime
        sample_points = [
            (-360, 24.2, 88.5, 66.0, 1780, 0),
            (-330, 24.0, 89.2, 65.5, 1795, 0),
            (-300, 24.4, 87.8, 65.0, 1810, 0),
            (-270, 25.1, 86.0, 64.2, 1830, 0),
            (-240, 26.3, 82.4, 63.5, 1850, 0),
            (-210, 27.5, 78.0, 62.8, 1870, 0),
            (-180, 28.4, 74.5, 61.9, 1895, 0),
            (-150, 29.1, 71.2, 61.0, 1920, 0),
            (-120, 29.6, 69.0, 60.2, 1940, 0),
            (-90, 29.8, 68.2, 59.5, 1960, 0),
            (-60, 29.4, 70.1, 58.8, 1980, 0),
            (-30, 29.0, 72.0, 61.5, 1910, 0),
            (0, 28.8, 73.2, 62.4, 1885, 0),
        ]
        for mins_ago, temp, rh, soil, adc, spike in sample_points:
            ts = (now + timedelta(minutes=mins_ago)).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute(
                """
                INSERT INTO telemetry (timestamp, temperature, humidity, soil_moisture, adc_raw, node_id, post_rain_heat_spike)
                VALUES (?, ?, ?, ?, ?, 'ESP32-FIELD-01', ?)
                """,
                (ts, temp, rh, soil, adc, spike),
            )

    conn.commit()
    conn.close()


def get_farm_settings() -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM farm_settings WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return {}
    data = dict(row)
    # Calculate active HST
    try:
        plant_dt = datetime.strptime(data["planting_date"], "%Y-%m-%d").date()
        auto_hst = max(1, (datetime.now().date() - plant_dt).days + 1)
    except Exception:
        auto_hst = 16

    data["auto_hst"] = auto_hst
    data["active_hst"] = (
        int(data["manual_hst_override"])
        if data["manual_hst_override"] is not None
        else auto_hst
    )
    return data


def update_farm_settings(
    planting_date: Optional[str] = None,
    manual_hst_override: Optional[int] = None,
    clear_hst_override: bool = False,
    variety: Optional[str] = None,
    plot_name: Optional[str] = None,
    demo_scenario: Optional[str] = None,
    led_brightness_pwm: Optional[int] = None,
) -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    current = get_farm_settings()

    new_planting = planting_date if planting_date is not None else current["planting_date"]
    if clear_hst_override:
        new_override = None
    elif manual_hst_override is not None:
        new_override = int(manual_hst_override)
    else:
        new_override = current.get("manual_hst_override")

    new_variety = variety if variety is not None else current["variety"]
    new_plot = plot_name if plot_name is not None else current["plot_name"]
    new_demo = demo_scenario if demo_scenario is not None else current["demo_scenario"]
    new_pwm = (
        int(led_brightness_pwm)
        if led_brightness_pwm is not None
        else current["led_brightness_pwm"]
    )

    cur.execute(
        """
        UPDATE farm_settings
        SET planting_date = ?,
            manual_hst_override = ?,
            variety = ?,
            plot_name = ?,
            demo_scenario = ?,
            led_brightness_pwm = ?
        WHERE id = 1
        """,
        (new_planting, new_override, new_variety, new_plot, new_demo, new_pwm),
    )
    conn.commit()
    conn.close()
    return get_farm_settings()


def insert_telemetry(
    temperature: float,
    humidity: float,
    soil_moisture: float,
    adc_raw: int = 2000,
    node_id: str = "ESP32-FIELD-01",
    post_rain_heat_spike: int = 0,
) -> Dict[str, Any]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO telemetry (timestamp, temperature, humidity, soil_moisture, adc_raw, node_id, post_rain_heat_spike)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_str,
            round(float(temperature), 1),
            round(float(humidity), 1),
            round(float(soil_moisture), 1),
            int(adc_raw),
            node_id,
            int(post_rain_heat_spike),
        ),
    )
    row_id = cur.lastrowid
    cur.execute(
        "UPDATE farm_settings SET esp32_last_seen = ? WHERE id = 1", (now_str,)
    )
    conn.commit()
    conn.close()
    return {
        "id": row_id,
        "timestamp": now_str,
        "temperature": round(float(temperature), 1),
        "humidity": round(float(humidity), 1),
        "soil_moisture": round(float(soil_moisture), 1),
        "adc_raw": int(adc_raw),
        "node_id": node_id,
        "post_rain_heat_spike": int(post_rain_heat_spike),
    }


def get_latest_telemetry() -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM telemetry ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "id": 0,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "temperature": 28.8,
        "humidity": 73.2,
        "soil_moisture": 62.4,
        "adc_raw": 1885,
        "node_id": "ESP32-FIELD-01",
        "post_rain_heat_spike": 0,
    }


def get_telemetry_history(limit: int = 30) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM telemetry ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    rows.reverse()
    return rows


def get_recent_telemetry_window(hours: int = 6) -> List[Dict[str, Any]]:
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM telemetry WHERE timestamp >= ? ORDER BY id ASC", (cutoff,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def insert_inspection(record: Dict[str, Any]) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO inspections (
            timestamp, hst, variety,
            img_top_orig, img_top_mask, img_top_stage,
            img_bottom_orig, img_bottom_mask, img_bottom_stage,
            gating_top_class, gating_top_conf,
            gating_bottom_class, gating_bottom_conf,
            severity_top, severity_bottom, severity_final,
            severity_category, pathogen_detected, latency_ms,
            temperature, humidity, soil_moisture, post_rain_heat_spike,
            decision_code, decision_title, decision_level,
            recommendation, action_steps_json, pipeline_metrics_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            record.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            int(record["hst"]),
            record["variety"],
            record["img_top_orig"],
            record["img_top_mask"],
            record.get("img_top_stage", ""),
            record["img_bottom_orig"],
            record["img_bottom_mask"],
            record.get("img_bottom_stage", ""),
            record["gating_top_class"],
            float(record["gating_top_conf"]),
            record["gating_bottom_class"],
            float(record["gating_bottom_conf"]),
            float(record["severity_top"]),
            float(record["severity_bottom"]),
            float(record["severity_final"]),
            record["severity_category"],
            record["pathogen_detected"],
            float(record["latency_ms"]),
            float(record["temperature"]),
            float(record["humidity"]),
            float(record["soil_moisture"]),
            int(record.get("post_rain_heat_spike", 0)),
            record["decision_code"],
            record["decision_title"],
            record["decision_level"],
            record["recommendation"],
            json.dumps(record.get("action_steps", []), ensure_ascii=False),
            json.dumps(record.get("pipeline_metrics", {}), ensure_ascii=False),
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_inspection_history(limit: int = 25) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inspections ORDER BY id DESC LIMIT ?", (limit,))
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        try:
            d["action_steps"] = json.loads(d.get("action_steps_json") or "[]")
        except Exception:
            d["action_steps"] = []
        try:
            d["pipeline_metrics"] = json.loads(d.get("pipeline_metrics_json") or "{}")
        except Exception:
            d["pipeline_metrics"] = {}
        rows.append(d)
    conn.close()
    return rows
