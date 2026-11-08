import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests


# Настройки
API_URL = os.getenv(
    "OBOD_API_URL",
    "https://asivoy.pythonanywhere.com/api"
).rstrip("/")

TEAM_KEY = os.getenv("OBOD_TEAM_KEY", "")
TOMTOM_KEY = os.getenv("TOMTOM_API_KEY", "")
TIMEZONE = ZoneInfo("Asia/Tashkent")

REQUEST_PAUSE_SECONDS = 0.25
MAX_POINTS = int(os.getenv("MAX_POINTS", "0"))  # 0 — все точки


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    if not response.ok:
        print(f"HTTP статус: {response.status_code}")
        print(f"Ответ сервера: {response.text[:2000]}")

        raise RuntimeError(
            f"Ошибка API: HTTP {response.status_code}"
        )

    return response.json()


def get_site_records():
    data = get_json(API_URL, params={"key": TEAM_KEY})

    if not data.get("ok"):
        raise RuntimeError(
            f"Ошибка API сайта: {data.get('error', 'неизвестная ошибка')}"
        )

    return data.get("records", [])


def get_tomtom_speed(lat, lon):
    url = (
        "https://api.tomtom.com/traffic/services/4/"
        "flowSegmentData/absolute/10/json"
    )

    data = get_json(
        url,
        params={
            "point": f"{lat},{lon}",
            "unit": "KMPH",
            "key": TOMTOM_KEY,
        },
    )

    flow = data.get("flowSegmentData") or {}

    current_speed = flow.get("currentSpeed")
    free_flow_speed = flow.get("freeFlowSpeed")

    if current_speed is None:
        raise ValueError("TomTom не вернул текущую скорость")

    current_speed = round(float(current_speed), 1)

    if free_flow_speed is not None:
        free_flow_speed = round(float(free_flow_speed), 1)

    return current_speed, free_flow_speed


def make_record(node, speed, free_flow, moment):
    local_time = moment.astimezone(TIMEZONE)

    # Интервал сбора — 20 минут
    minute_bucket = (local_time.minute // 20) * 20

    start = local_time.replace(
        minute=minute_bucket,
        second=0,
        microsecond=0
    )

    end = start + timedelta(minutes=20)

    record_id = (
        f"tomtom-{node['id']}-"
        f"{start.strftime('%Y%m%d%H%M')}"
    )

    comment = "Автоматический замер TomTom"

    if free_flow is not None:
        comment += f"; свободная скорость {free_flow} км/ч"

    return {
        "id": record_id,
        "kind": "record",
        "created": local_time.isoformat(),
        "updated": int(time.time() * 1000),
        "date": start.strftime("%Y-%m-%d"),
        "hour": start.hour,
        "timeFrom": start.strftime("%H:%M"),
        "timeTo": end.strftime("%H:%M"),
        "street": node.get("street", ""),
        "cross": node.get("cross", ""),
        "tuman": node.get("tuman", ""),
        "mahallaId": node.get("mahallaId", ""),
        "mahallaName": node.get("mahallaName", ""),
        "nodeId": node["id"],
        "point": node.get("point"),
        "speed": speed,
        "length": None,
        "ball": None,
        "severity": 2,
        "causes": [],
        "comment": comment,
        "idea": "",
        "status": "idea",
        "author": "TomTom Auto",
        "betweenIds": [],
        "source": "tomtom",
    }


def save_records(records):
    payload = {
        "key": TEAM_KEY,
        "records": records,
    }

    response = requests.post(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False),
        headers={
            "Content-Type": "text/plain;charset=utf-8"
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Сайт не сохранил записи: {data.get('error', 'ошибка')}"
        )

    return data.get("saved", 0)


def run_once():
    all_records = get_site_records()

    nodes = [
        item for item in all_records
        if item.get("kind") == "node"
        and isinstance(item.get("point"), (list, tuple))
        and len(item["point"]) >= 2
        and item["point"][0] is not None
        and item["point"][1] is not None
        and not item.get("deleted")
    ]

    if MAX_POINTS > 0:
        nodes = nodes[:MAX_POINTS]

    if not nodes:
        print("Не найдено перекрёстков с координатами.")
        return

    moment = datetime.now(TIMEZONE)

    print(f"Время Ташкента: {moment:%Y-%m-%d %H:%M:%S}")
    print(f"Перекрёстков для обработки: {len(nodes)}")

    results = []
    errors = []

    for index, node in enumerate(nodes, start=1):
        point = node["point"]
        lat = float(point[0])
        lon = float(point[1])

        name = (
            f"{node.get('street', '?')} × "
            f"{node.get('cross', '?')}"
        )

        try:
            speed, free_flow = get_tomtom_speed(lat, lon)

            results.append(
                make_record(node, speed, free_flow, moment)
            )

            print(
                f"[{index}/{len(nodes)}] {name}: "
                f"{speed} км/ч"
            )

        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"[{index}/{len(nodes)}] Ошибка: {exc}")

        time.sleep(REQUEST_PAUSE_SECONDS)

    if results:
        saved = save_records(results)

        print(
            f"\nСайт сохранил {saved} записей "
            f"из {len(results)} полученных."
        )
    else:
        print("\nНет успешных замеров для отправки.")

    if errors:
        print(f"\nНе удалось получить скорость для {len(errors)} точек.")


def main():
    if not TEAM_KEY:
        raise SystemExit("Не задан секрет OBOD_TEAM_KEY.")

    if not TOMTOM_KEY:
        raise SystemExit("Не задан секрет TOMTOM_API_KEY.")

    run_once()


if __name__ == "__main__":
    main()
