# processing.py
import os
import math
import cv2
import numpy as np
import pandas as pd


def create_tracker(name: str = "CSRT"):
    """
    嘗試建立 OpenCV 追蹤器（支援 legacy 與非 legacy 命名）。
    順序：CSRT -> KCF -> MOSSE
    """
    name = (name or "CSRT").upper()
    candidates = []

    # 優先嘗試 legacy 名稱（4.5+ 常見）
    candidates.append(lambda: getattr(cv2, "legacy").__getattribute__(f"Tracker{name}_create")())
    # 再嘗試非 legacy 舊名稱
    candidates.append(lambda: getattr(cv2, f"Tracker{name}_create")())

    # 若指定的 name 失敗，換其它
    for alt in ["KCF", "MOSSE"]:
        candidates.append(lambda alt=alt: getattr(cv2, "legacy").__getattribute__(f"Tracker{alt}_create")())
        candidates.append(lambda alt=alt: getattr(cv2, f"Tracker{alt}_create")())

    for ctor in candidates:
        try:
            return ctor()
        except Exception:
            continue

    raise RuntimeError(
        "OpenCV 追蹤器不可用。請確認已安裝 opencv-contrib-python(-headless) 並版本相符。"
    )


def _normalize_bbox(bbox_raw, frame_shape):
    """
    接受格式：
      - dict: {x,y,w,h} 或 {x1,y1,x2,y2}
      - list/tuple: [x,y,w,h] 或 [x1,y1,x2,y2] 或 [[x1,y1],[x2,y2]]
    一律回傳 (x, y, w, h) 的純 Python float，並裁剪到影像範圍、w/h 至少 1。
    """
    H, W = frame_shape[:2]

    # 解析輸入
    if isinstance(bbox_raw, dict):
        if all(k in bbox_raw for k in ("x", "y", "w", "h")):
            x, y, w, h = bbox_raw["x"], bbox_raw["y"], bbox_raw["w"], bbox_raw["h"]
        elif all(k in bbox_raw for k in ("x1", "y1", "x2", "y2")):
            x1, y1, x2, y2 = bbox_raw["x1"], bbox_raw["y1"], bbox_raw["x2"], bbox_raw["y2"]
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
        else:
            raise ValueError(f"bbox 鍵缺少必要欄位: {bbox_raw}")
    elif isinstance(bbox_raw, (list, tuple)) and len(bbox_raw) == 4:
        # 可能是 [x,y,w,h] 或 [x1,y1,x2,y2]（後者會在下面判斷）
        a, b, c, d = bbox_raw
        # 嘗試判斷是不是兩點座標（寬高為負或非常大時也會在裁剪時修正）
        if min(c, d) < 0 or (a <= 1 and b <= 1 and c <= 1 and d <= 1):
            # 太多猜測情境，統一視為 x,y,w,h，交給邊界裁剪處理
            x, y, w, h = a, b, c, d
        else:
            # 多數情況直接當 x,y,w,h 使用
            x, y, w, h = a, b, c, d
    elif isinstance(bbox_raw, (list, tuple)) and len(bbox_raw) == 2 \
            and all(isinstance(v, (list, tuple)) and len(v) == 2 for v in bbox_raw):
        # [[x1,y1],[x2,y2]]
        (x1, y1), (x2, y2) = bbox_raw
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
    else:
        raise ValueError(f"bbox 格式不支援: {bbox_raw}")

    # 轉純 float
    try:
        x = float(x); y = float(y); w = float(w); h = float(h)
    except Exception as e:
        raise ValueError(f"bbox 內含非數值: {bbox_raw}") from e

    # 非數值檢查
    for v in (x, y, w, h):
        if not math.isfinite(v):
            raise ValueError(f"bbox 含 NaN/Inf: {(x, y, w, h)}")

    # 最小尺寸
    w = max(1.0, w)
    h = max(1.0, h)

    # 邊界裁剪
    x = max(0.0, min(x, W - 1.0))
    y = max(0.0, min(y, H - 1.0))
    w = max(1.0, min(w, W - x))
    h = max(1.0, min(h, H - y))

    return (float(x), float(y), float(w), float(h))


def extract_first_frame(video_path: str, tmp_folder: str, job_id: str):
    cap = cv2.VideoCapture(video_path)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    os.makedirs(tmp_folder, exist_ok=True)
    out_path = os.path.join(tmp_folder, f"{job_id}_first.png")
    cv2.imwrite(out_path, frame)
    return out_path


def run_tracking(video_path: str, result_dir: str, scale_cm: float, p1: dict, p2: dict, bbox):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video.")

    # 影片參數
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 30.0
    width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0))
    height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
    if width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError("Video width/height 讀取失敗。")
    dt = 1.0 / fps

    # 比例尺：像素 -> 公尺
    p1v = np.array([float(p1["x"]), float(p1["y"])], dtype=float)
    p2v = np.array([float(p2["x"]), float(p2["y"])], dtype=float)
    pixel_dist = float(np.linalg.norm(p1v - p2v))
    if pixel_dist <= 1e-9:
        cap.release()
        raise ValueError("比例尺端點太近（距離為 0），請重新標定。")
    pixel_to_meter = (float(scale_cm) / 100.0) / pixel_dist  # meters per pixel

    # 第一幀
    ok, first = cap.read()
    if not ok or first is None:
        cap.release()
        raise RuntimeError("Cannot read first frame.")

    # 追蹤器
    tracker = create_tracker()
    init_box = _normalize_bbox(bbox, first.shape)

    ok = tracker.init(first, init_box)
    if not ok:
        cap.release()
        raise RuntimeError(f"追蹤器 init 失敗，bbox={init_box}")

    # 輸出影片
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    os.makedirs(result_dir, exist_ok=True)
    out_video_path = os.path.join(result_dir, "tracked.mp4")
    writer = cv2.VideoWriter(out_video_path, fourcc, fps, (int(width), int(height)))

    # 追蹤狀態
    prev_pos = None
    prev_speed = None
    rows = []

    # 回到第 0 幀
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break

        ok, box = tracker.update(frame)
        if not ok or box is None:
            # 追丟就寫入原始框（不畫十字）
            writer.write(frame)
            # 仍記錄時間（但不寫位移/速度）
            t = (cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
            rows.append({
                "time": round(t, 3),
                "x": "",
                "y": "",
                "vx": "",
                "vy": "",
                "ax": "",
                "ay": ""
            })
            continue

        x, y, w, h = map(float, box)
        cx = x + w / 2.0
        cy = y + h / 2.0
        xm = cx * pixel_to_meter
        ym = cy * pixel_to_meter

        # 速度/加速度
        speed = acceleration = None
        if prev_pos is not None:
            vx = (xm - prev_pos[0]) / dt
            vy = (ym - prev_pos[1]) / dt
            speed = (vx, vy)
            if prev_speed is not None:
                ax = (vx - prev_speed[0]) / dt
                ay = (vy - prev_speed[1]) / dt
                acceleration = (ax, ay)
            prev_speed = (vx, vy)
        prev_pos = (xm, ym)

        # 時間戳
        t = (cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0

        rows.append({
            "time": round(t, 3),
            "x": round(xm, 4),
            "y": round(ym, 4),
            "vx": round(speed[0], 4) if speed else "",
            "vy": round(speed[1], 4) if speed else "",
            "ax": round(acceleration[0], 4) if acceleration else "",
            "ay": round(acceleration[1], 4) if acceleration else ""
        })

        # 畫紅色十字與外框
        cv2.rectangle(frame, (int(x), int(y)), (int(x + w), int(y + h)), (0, 255, 0), 2)
        cv2.line(frame, (int(cx - 10), int(cy - 10)), (int(cx + 10), int(cy + 10)), (0, 0, 255), 2)
        cv2.line(frame, (int(cx - 10), int(cy + 10)), (int(cx + 10), int(cy - 10)), (0, 0, 255), 2)

        writer.write(frame)

    cap.release()
    writer.release()

    # 輸出 CSV
    out_csv_path = os.path.join(result_dir, "track.csv")
    pd.DataFrame(rows).to_csv(out_csv_path, index=False)

    return out_video_path, out_csv_path
