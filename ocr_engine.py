import os
import json
import re
import copy
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd

# Imaging / OCR dependencies (required)
import cv2  # OpenCV for image processing
from PIL import Image  # Pillow for image handling
import easyocr  # EasyOCR for text recognition

# Resolve key paths relative to this module so demo assets load regardless of cwd
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(HERE, "assets")

# Output paths for saving parsed data
OUT_DIR = os.path.join(HERE, "userdata")  # Directory where all output files will be stored
RAW_PATH = os.path.join(OUT_DIR, "raw_ocr.txt")  # Raw OCR output text
CSV_PATH = os.path.join(OUT_DIR, "shifts.csv")  # Parsed shifts in CSV format
JSON_PATH = os.path.join(OUT_DIR, "shifts.json")  # Parsed shifts in JSON format
XLSX_PATH = os.path.join(OUT_DIR, "shifts.xlsx")  # Parsed shifts in Excel format
DEBUG_PATH = os.path.join(OUT_DIR, "parsed_debug.txt")  # Debug information
SAMPLE_JSON = os.path.join(ASSETS_DIR, "sample_shifts.json")  # Prefab demo data
SAMPLE_RAW_OCR = os.path.join(ASSETS_DIR, "sample_raw_ocr.txt")  # Prefab OCR text

# Inline fallbacks so prefab mode still works even if assets are missing at runtime
FALLBACK_SAMPLE_PARSED = {
    "person": "NINA ARONOVA",
    "year": 2025,
    "month": 12,
    "days": list(range(1, 32)),
    "records": [
        {"person": "NINA ARONOVA", "date": "2025-12-02", "shift_code": "M", "shift_type": "Morning", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-04", "shift_code": "T", "shift_type": "Evening", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-07", "shift_code": "N", "shift_type": "Night", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-10", "shift_code": "M", "shift_type": "Morning", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-12", "shift_code": "T", "shift_type": "Evening", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-15", "shift_code": "N", "shift_type": "Night", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-18", "shift_code": "M", "shift_type": "Morning", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-21", "shift_code": "T", "shift_type": "Evening", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-24", "shift_code": "N", "shift_type": "Night", "hours": 8},
        {"person": "NINA ARONOVA", "date": "2025-12-28", "shift_code": "M", "shift_type": "Morning", "hours": 8},
    ],
}

FALLBACK_SAMPLE_RAW = "\n".join(
    [
        "Name (conf=1.00)",
        "1 L (conf=0.87)",
        "2 M (conf=0.93)",
        "3 X (conf=0.95)",
        "4] (conf=0.48)",
        "5 V (conf=0.81)",
        "6 5 (conf=0.93)",
        "7 D (conf=0.77)",
        "LVIRA JIMENET (conf=0.80)",
        "M (conf=1.00)",
        "IOLA MIQUELI (conf=0.71)",
        "N (conf=0.43)",
        "oaarawovl (conf=0.13)",
        "N (conf=0.12)",
        "M (conf=0.74)",
        "M (conf=0.59)",
        " (conf=0.00)",
        " (conf=0.00)",
        " (conf=0.00)",
        '" (conf=0.02)',
        '" (conf=0.07)',
    ]
)

# Configuration variables
TARGET_NAME = os.environ.get("TARGET_NAME", "NINA ARONOVA")  # Name to look for in schedule
SHIFT_MAP = {  # Mapping of shift codes to shift details
    "M": ("Morning", 6, 14),  # Morning shift: 6 AM to 2 PM
    "T": ("Evening", 14, 22),  # Evening shift: 2 PM to 10 PM
    "N": ("Night", 22, 6)  # Night shift: 10 PM to 6 AM (next day)
}
MIN_TOKEN_CONFIDENCE = 0.15  # Minimum confidence to consider a token in parsing logic

# Global variable to store the EasyOCR reader instance
_reader = None


def _get_reader():

    #Initialize and return the EasyOCR reader.

    global _reader
    if _reader is None:
        # Initialize the reader for English language, without GPU acceleration
        _reader = easyocr.Reader(['en'], gpu=False)
    return _reader


def _prepare_for_ocr(cv_img):
    """
    Improve image readability for OCR by boosting contrast and reducing noise.

    A CLAHE pass makes faint table text easier to pick up, while a light
    denoise step prevents artifacts from being amplified when the contrast is
    increased.
    """
    if cv_img is None:
        raise ValueError("cv_img is required for preprocessing")

    if len(cv_img.shape) == 3 and cv_img.shape[2] == 3:
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    else:
        gray = cv_img

    # Upscale smaller images so that faint numbers and letters are more legible
    h, w = gray.shape[:2]
    long_side = max(h, w)
    if long_side < 1800:
        scale = 1800 / long_side
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    denoised = cv2.fastNlMeansDenoising(enhanced, h=10, templateWindowSize=7, searchWindowSize=21)

    # Adaptive thresholding boosts low-contrast table entries without erasing strokes
    binary = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        9,
    )
    return binary


def _run_easyocr(cv_img, detail=1):
    """
    Run EasyOCR with consistent preprocessing and relaxed detection thresholds.

    The low_text and text_threshold parameters are aligned to 0.25 to make the
    detector more permissive for faint table entries.
    """
    reader = _get_reader()
    prepared = _prepare_for_ocr(cv_img)
    return reader.readtext(
        prepared,
        detail=detail,
        text_threshold=0.25,
        low_text=0.25,
        link_threshold=0.3,
    )


def _read_image(path):
    """
    Read an image from file and convert it to formats suitable for OpenCV and PIL.
    Returns both PIL Image and OpenCV image formats.
    """
    pil = Image.open(path).convert("RGB")  # Open image with PIL and ensure RGB format
    # Convert PIL image to OpenCV format (BGR instead of RGB)
    cv_img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return pil, cv_img


def dump_raw_ocr(path):
    """
    Perform raw OCR on an image and return the text with confidence scores.
    This function doesn't try to parse the structure, just extracts all text.
    """
    if not os.path.exists(path):
        return f"[ERROR] File not found: {path}"

    # Read the image
    pil, cv_img = _read_image(path)

    # Perform OCR on the image with preprocessing and relaxed thresholds
    res = _run_easyocr(cv_img)

    # Format the results with text and confidence scores
    lines = []
    for item in res:
        if len(item) == 3:
            _, text, conf = item
            lines.append(f"{text} (conf={conf:.2f})")
        else:
            lines.append(str(item))

    return "\n".join(lines)


def load_sample_raw_text():
    """Load the prefab raw OCR text used for demo mode displays."""
    try:
        if os.path.exists(SAMPLE_RAW_OCR):
            with open(SAMPLE_RAW_OCR, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        pass
    return FALLBACK_SAMPLE_RAW


def save_raw_text(text):
    """
    Save the raw OCR text to a file for debugging purposes.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(RAW_PATH, "w", encoding="utf-8") as f:
        f.write(text or "")
    return RAW_PATH


def load_sample_parsed():
    """Load prefab parsed shifts for demo mode with a built-in fallback."""
    try:
        if os.path.exists(SAMPLE_JSON):
            with open(SAMPLE_JSON, "r", encoding="utf-8") as f:
                parsed = json.load(f)
                if parsed.get("records"):
                    return parsed
    except Exception:
        pass

    # Return a defensive copy so callers can't mutate the shared fallback
    return copy.deepcopy(FALLBACK_SAMPLE_PARSED)


def load_saved_outputs(use_prefab_data=False):
    """Return the most recently saved parsed shifts.

    Args:
        use_prefab_data: When ``True``, fall back to prefab demo data if no saved
            JSON exists. When ``False``, return ``None`` when no user data is
            available so the UI can prompt for a first upload.

    Returns:
        A tuple of (status_message, parsed_dict or None)
    """
    parsed = None
    info = "Upload an image to get started."

    try:
        if os.path.exists(JSON_PATH):
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                parsed = json.load(f)
                if parsed:
                    info = "Loaded saved shifts from your last upload."
    except Exception:
        parsed = None
        info = "Saved shifts could not be loaded."

    if parsed is None and use_prefab_data:
        parsed = load_sample_parsed()
        info = "Loaded prefab sample shifts."

    return info, parsed


def parse_schedule(cv_img):
    """
    Main function to parse a schedule image.
    This function uses the bounding box method to extract shifts for the target person.
    """
    today = date.today()
    year, month = today.year, today.month

    # Assume a standard month with up to 31 days
    days = list(range(1, 32))

    # Use the bounding box method to parse the schedule
    parsed = _bbox_map_parse(cv_img, days)

    if parsed is None:
        # Return an empty structure instead of raising so the UI can continue
        # running and surface a helpful status message to the user.
        return {
            "person": TARGET_NAME,
            "year": year,
            "month": month,
            "days": days,
            "records": [],
        }

    return parsed


def _bbox_map_parse(cv_img, days):
    """
    Parse schedule using EasyOCR bounding boxes.
    This method:
    1. Finds all text in the image with their positions
    2. Locates the target person's name
    3. Finds shift codes (M, T, N) near the target's row
    4. Maps shift codes to days based on their horizontal position
    """
    # Perform OCR with detailed information (including bounding boxes)
    res = _run_easyocr(cv_img, detail=1)  # Returns (bbox, text, confidence)
    if not res:
        return None

    # Process each detected text token
    tokens = []
    for bbox, text, conf in res:
        if float(conf) < MIN_TOKEN_CONFIDENCE:
            continue
        # bbox contains 4 points: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        # Calculate center point of the bounding box
        xs_bbox = [pt[0] for pt in bbox]
        ys_bbox = [pt[1] for pt in bbox]
        cx = sum(xs_bbox) / 4.0  # Center X coordinate
        cy = sum(ys_bbox) / 4.0  # Center Y coordinate

        # Store token information
        tokens.append({"text": text.strip(), "conf": float(conf), "cx": cx, "cy": cy})

    # Step 1: Find the target person's name in the detected text
    target_candidates = [t for t in tokens if TARGET_NAME.upper() in t["text"].upper()]

    # If exact match not found, try fuzzy matching on first name
    if not target_candidates:
        first = TARGET_NAME.split()[0]
        target_candidates = [t for t in tokens if first and first.upper() in t["text"].upper()]

    if not target_candidates:
        return None  # Target person not found in the schedule

    # Select the candidate with highest confidence
    target = max(target_candidates, key=lambda x: x["conf"])
    target_y = target["cy"]  # Y-coordinate of the target's row

    # Step 2: Calculate vertical tolerance for finding elements in the same row
    # This helps account for slight variations in text positioning
    ys_centers = sorted({int(round(t["cy"])) for t in tokens})
    if len(ys_centers) >= 2:
        # Calculate median gap between text rows
        gaps = [ys_centers[i + 1] - ys_centers[i] for i in range(len(ys_centers) - 1)]
        median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 40
        y_tol = max(25, int(median_gap * 0.8))  # More lenient tolerance for noisy scans
    else:
        y_tol = 35  # Default tolerance

    # Step 3: Find day numbers in the header (above the target's row)
    day_tokens = []
    for t in tokens:
        # Look for tokens with digits that are above the target's row
        if t["cy"] < target_y - y_tol and re.search(r"\d+", t["text"]):
            day_tokens.append(t)

    # Sort day tokens by their X position (left to right)
    day_tokens.sort(key=lambda x: x["cx"])

    # Step 4: Map day numbers to X positions
    if day_tokens:
        # If we found day tokens, use them to establish X positions
        day_x_map = {}
        for i, day in enumerate(days):
            if i < len(day_tokens):
                day_x_map[day] = day_tokens[i]["cx"]
            else:
                # For days beyond detected tokens, estimate position
                img_w = cv_img.shape[1]
                day_x_map[day] = (i + 0.5) * img_w / len(days)
    else:
        # If no day tokens found, assume equal spacing across the image
        img_w = cv_img.shape[1]
        day_x_map = {day: (i + 0.5) * img_w / len(days) for i, day in enumerate(days)}

    # Step 5: Find shift codes in the same row as the target
    shift_tokens = []
    for t in tokens:
        # Look for tokens containing M, T, or N that are in the same row as the target
        if abs(t["cy"] - target_y) < y_tol and re.search(r"[MTN]", t["text"].upper()):
            shift_tokens.append(t)

    # Step 6: Map shift codes to days based on X position
    day_shift_map = {}
    for t in shift_tokens:
        # Find the day whose X position is closest to this shift token
        closest_day = min(days, key=lambda d: abs(t["cx"] - day_x_map[d]))

        # Extract the shift code (M, T, or N)
        m = re.search(r"[MTN]", t["text"].upper())
        code = m.group(0) if m else ""

        if code in SHIFT_MAP:
            # Keep the highest confidence token for each day
            if closest_day not in day_shift_map or t["conf"] > day_shift_map[closest_day][1]:
                day_shift_map[closest_day] = (code, t["conf"])

    # Step 7: Build the parsed records with shift information
    today = date.today()
    year, month = today.year, today.month
    parsed = {
        "person": TARGET_NAME,
        "year": year,
        "month": month,
        "days": days,
        "records": []
    }

    for day, (code, conf) in day_shift_map.items():
        shift_type, start_h, end_h = SHIFT_MAP[code]

        try:
            dt = date(year, month, int(day))
        except Exception:
            continue  # Skip invalid dates

        # Calculate shift times based on shift type
        if shift_type == "Night":
            # Night shift spans two days (10 PM to 6 AM)
            start_dt = datetime(year, month, dt.day, 22, 0)
            end_dt = start_dt + timedelta(hours=8)
            hours = 8
        else:
            # Day shifts are within the same day
            start_dt = datetime(year, month, dt.day, start_h, 0)
            end_dt = datetime(year, month, dt.day, end_h, 0)
            hours = end_h - start_h

        # Create a record for this shift
        rec = {
            "person": TARGET_NAME,
            "date": dt.isoformat(),
            "dow": dt.strftime("%a"),  # Day of week abbreviation
            "shift_code": code,
            "shift_type": shift_type,
            "start": start_dt.strftime("%Y-%m-%d %H:%M"),
            "end": end_dt.strftime("%Y-%m-%d %H:%M"),
            "hours": hours
        }
        parsed["records"].append(rec)

    # Save debug information
    _write_debug(tokens, parsed)
    return parsed


def _write_debug(tokens, parsed):
    """
    Save debug information about the parsing process.
    This helps with troubleshooting when the parsing doesn't work as expected.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = []

    lines.append(
        f"tokens_total={len(tokens)} | records_found={len(parsed.get('records', []))}"
    )

    # Add information about all detected tokens
    lines.append(f"=== TOKENS SAMPLE (min_conf={MIN_TOKEN_CONFIDENCE}) ===")
    for t in tokens[:200]:  # Limit to first 200 tokens to avoid huge files
        lines.append(f"{t['text']} (conf={t['conf']:.2f}) cx={t['cx']:.1f} cy={t['cy']:.1f}")

    # Add the parsed result
    lines.append("\n=== PARSED ===")
    lines.append(json.dumps(parsed, ensure_ascii=False, indent=2))

    # Write to debug file
    with open(DEBUG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def save_outputs(parsed):
    """
    Save the parsed shifts to multiple file formats (CSV, JSON, Excel).
    This provides output in various formats for different use cases.
    """
    os.makedirs(OUT_DIR, exist_ok=True)

    # Convert to DataFrame for easier manipulation
    df = pd.DataFrame(parsed.get("records", []))

    # Save as CSV
    try:
        df.to_csv(CSV_PATH, index=False, encoding="utf-8")
    except Exception:
        # Create empty file if CSV saving fails
        with open(CSV_PATH, "w", encoding="utf-8") as f:
            f.write("")

    # Save as JSON
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    # Save as Excel (if openpyxl is available)
    try:
        with pd.ExcelWriter(XLSX_PATH, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Shifts")
    except Exception:
        pass  # Skip Excel export if it fails


def process_image(path):
    """
    Main function to process a schedule image.
    Handles the entire workflow from image to parsed shifts.
    Returns: (raw_text, status_message, parsed_data)
    """
    # Check if file exists
    if not os.path.exists(path):
        return "[ERROR] File not found.", "Status: file missing", None

    # Step 1: Perform raw OCR and save results
    try:
        raw_text = dump_raw_ocr(path)
    except Exception as e:
        raw_text = f"[ERROR] raw OCR failed: {e}"

    try:
        save_raw_text(raw_text)
    except Exception:
        pass  # Continue even if saving raw text fails

    # Step 2: Read the image for parsing
    try:
        pil, cv_img = _read_image(path)
    except Exception as e:
        return raw_text, f"[ERROR] Failed to open image: {e}", None

    # Step 3: Parse the schedule
    try:
        parsed = parse_schedule(cv_img)
        if parsed.get("records"):
            info = f"Status: parsed {len(parsed.get('records', []))} shifts for {parsed.get('person')}"
        else:
            info = (
                "Status: no shifts parsed. If this is December, double-check the "
                "name selection and month in the source image."
            )
    except Exception as e:
        parsed = {
            "person": TARGET_NAME,
            "year": date.today().year,
            "month": date.today().month,
            "days": [],
            "records": [],
        }
        info = f"[ERROR] Schedule parsing failed: {e}"

    # Step 4: Save outputs in various formats
    save_outputs(parsed)

    return raw_text, info, parsed
