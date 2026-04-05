# Scan Sure Backend (Django + MongoEngine)

This is a complete backend implementation built exactly to requirements, using global pip packages since `venv` was unused. 

### How to Run:
Since dependencies are already installed globally on your machine, just start the server:

```bash
python manage.py runserver
```

---

## 🚀 Postman / API Testing Guide

### 1. Upload a New Image (Create Scan)
**Endpoint:** `POST http://127.0.0.1:8000/api/scan/`  
**Content-Type:** `multipart/form-data`

**Request Body Setup in Postman:**
In Postman, switch body to **form-data** and add these three rows (Make sure to switch the type to **File** for the image row by hovering over the key field cell):

1. **Key:** `image` | **Value:** [Select File]
2. **Key:** `prediction_label` | **Value:** `Fake`
3. **Key:** `confidence_score` | **Value:** `0.85`

**cURL Example:**
```bash
curl -X POST http://127.0.0.1:8000/api/scan/ \
  -F "image=@C:/path/to/my_image.png" \
  -F "prediction_label=Real" \
  -F "confidence_score=0.99"
```

### 2. Fetch All Scans 
**Endpoint:** `GET http://127.0.0.1:8000/api/scan/`

**cURL Example:**
```bash
curl -X GET http://127.0.0.1:8000/api/scan/
```

### Technical Note on `django.db.backends.sqlite3` in Database Setting:
Even though the project uses `mongoengine` connected directly to MongoDB Atlas, Django's built-in framework features (like session cookies/admin panel login requirements) throw errors if `DATABASES` is entirely missing or null. A dummy fallback is provided, but your `ScanResult` instances are 100% saved into Atlas!
