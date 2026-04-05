import cv2
import pytesseract
import re
from difflib import get_close_matches
from pyzxing import BarCodeReader

# 👉 Set path (ONLY if Tesseract not in PATH)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

reader = BarCodeReader()

def extract_text(image_path):
    # Read image
    img = cv2.imread(image_path)
    if img is None:
        print("Error: Image not found")
        return ""
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Apply threshold (improves OCR)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    # OCR configuration
    config = r'--oem 3 --psm 6'
    # Extract text
    text = pytesseract.image_to_string(thresh, config=config)
    return text

import os
import shutil
import tempfile

def get_barcode(image_path):
    # Copy file to a temporary location without spaces to avoid pyzxing Java InvalidPathException
    _, ext = os.path.splitext(image_path)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(tmp_fd)
    
    try:
        shutil.copy(image_path, tmp_path)
        result = reader.decode(tmp_path)
        if result:
            barcode = result[0].get('parsed')
            if barcode:
                return barcode
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return None

BRANDS = [
    "mamaearth", "nivea", "lakme", "loreal", "ponds", "wow", "dove"
]

PRODUCTS = [
    "face wash", "shampoo", "conditioner", "serum", "cream"
]

INGREDIENTS_DICT = [
    "Turmeric", "Water", "Stearic Acid", "Cocamidopropyl", "Betaine",
    "Caprylyl/Capryl", "Glucoside Sodium Methyl Cocoyl", "Taurate", "Glycerin", "Sodium", "Lauroyl", "Sarcosinate", "Ethylene", "Glycol", "Distearate", "Potassium", "Hydroxide", "Lauric Acid", "Coconut Oil", "Myristic Acid", "Acrylates/Beheneth-25", "Methacrylate Copolymer", "Polysorbate 20", "Glyceryl Monostearate", "Polyquaternium 7", "D-Panthenol", "Walnut Beads", "Phenoxyethanol", "Ethylhexylglycerin", "Turmeric Powder", "Saffron Extract", "Xanthan Gum", "Titanium Dioxide", "IFRA Certified", "Fragrance", "Liquorice Extract", "Vitamin E", "Sodium Hydroxide", "Niacinamide", "Sodium Gluconate", "Butylated Hydroxytoluene", "Carrot Seed Oil", "Orange Oil", "Ylang Ylang Oil & Patchouli Oil",
    "Glycerin", "Dimethicone", "Shea Butter", "Ceramide NP", "Hyaluronic Acid (multiple forms)",
    "Soybean Oil", "Oat Extract", "Mineral Oil", "Cetearyl Alcohol", "Glyceryl Stearate", "Petrolatum",
    "Phenoxyethanol", "Methylparaben", "Propylparaben", "BHT", "Isopropyl Palmitate", "Myristyl Myristate",
    "Alkyl Benzoate", "Ceramide NP", "Sodium Hyaluronate", "Limonene", "Linalool", "Citronellol", "Hexyl Cinnamal",
    "Benzyl Salicylate", "Hydrolyzed Hyaluronic Acid", "Butane", "Isobutane", "Propane", "Ethyl Alcohol",
    "Propylene Glycol", "Triethyl Citrate", "Denatonium Benzoate", "glycerin", "niacinamide", "turmeric", "saffron",
    "coconut oil", "vitamin e", "panthenol", "salicylic acid", "stearic acid", "lauric acid"
]

def fuzzy_find(text, dictionary):
    found = []
    words = text.split()
    for word in words:
        match = get_close_matches(word, dictionary, n=1, cutoff=0.8)
        if match:
            found.append(match[0])
    return list(set(found))

def extract_brand(text):
    for brand in BRANDS:
        if brand in text:
            return brand
    match = fuzzy_find(text, BRANDS)
    return match[0] if match else None

def extract_product(text):
    for product in PRODUCTS:
        if product in text:
            return product
    return None

def extract_ingredients(text):
    found = []
    for ing in INGREDIENTS_DICT:
        if ing.lower() in text:
            found.append(ing)
    found += fuzzy_find(text, [i.lower() for i in INGREDIENTS_DICT])
    return list(set(found))

def extract_batch(text):
    match = re.findall(r'\b[a-z]{2,}\d+[a-z0-9]*\b', text)
    return match[0] if match else None

def process_image(image_path):
    text = extract_text(image_path)
    barcode = get_barcode(image_path)
    text_lower = text.lower()
    
    data = {
        "brand": extract_brand(text_lower),
        "product": extract_product(text_lower),
        "ingredients": extract_ingredients(text_lower),
        "barcode": barcode,
        "batch": extract_batch(text_lower),
        "raw_text": text
    }
    return data


def process_images(image_paths_list):
    """
    Process multiple images (e.g. front + back of a label) and merge their
    OCR results into one unified dict.
    
    Strategy:
      - Scalar fields (brand, product, barcode, batch): first non-None value wins.
      - Ingredients: union across all images (deduplicated, case-insensitive).
      - raw_text: concatenated with a separator.
    """
    merged = {
        "brand": None,
        "product": None,
        "ingredients": [],
        "barcode": None,
        "batch": None,
        "raw_text": ""
    }

    seen_ingredients = set()

    for path in image_paths_list:
        try:
            data = process_image(path)
        except Exception:
            continue  # skip unreadable images, don't crash the whole scan

        # Scalar fields: take first non-None value found across images
        for field in ("brand", "product", "barcode", "batch"):
            if merged[field] is None and data.get(field):
                merged[field] = data[field]

        # Ingredients: union, deduplicated
        for ing in (data.get("ingredients") or []):
            key = ing.strip().lower()
            if key and key not in seen_ingredients:
                seen_ingredients.add(key)
                merged["ingredients"].append(ing)

        # raw_text: concatenate (back label often has ingredients text)
        if data.get("raw_text"):
            separator = "\n--- [next image] ---\n" if merged["raw_text"] else ""
            merged["raw_text"] += separator + data["raw_text"]

    return merged


if __name__ == "__main__":
    pass