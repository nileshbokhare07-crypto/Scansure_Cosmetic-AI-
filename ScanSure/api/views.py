from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .models import ScanResult
import os
import uuid
from ocr import process_images
import predictor  # model-based Real/Fake predictor


class ScanAPIView(APIView):
    def post(self, request):
        """
        Accept one or more product images:
          image_front  — front of the product/label (or legacy field 'image')
          image_back   — back of the label (ingredients side)  [optional]
          image_3 … image_5                                   [optional]
          prediction_label — hint from frontend ('Real'/'Fake'/'Unknown'); overridden by model
          confidence_score — hint from frontend; overridden by model
        """
        try:
            # ── Collect all supplied image files ─────────────────────────────
            image_fields = ['image_front', 'image_back', 'image_3', 'image_4', 'image_5']
            image_files = []

            # Legacy single-image support
            legacy = request.FILES.get('image')
            if legacy:
                image_files.append(('front', legacy))

            for field in image_fields:
                f = request.FILES.get(field)
                if f:
                    label = field.replace('image_', '')
                    image_files.append((label, f))

            if not image_files:
                return Response(
                    {"error": "No image supplied. Provide at least image_front (or legacy field 'image')."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # ── Save every image to media/scans/ ────────────────────────────
            media_path = os.path.join(settings.MEDIA_ROOT, 'scans')
            os.makedirs(media_path, exist_ok=True)

            saved_paths  = []   # absolute filesystem paths (for OCR)
            relative_paths = [] # relative to MEDIA_ROOT   (for DB)

            for label, img_file in image_files:
                ext = os.path.splitext(img_file.name)[1]
                unique_name = f"{uuid.uuid4()}_{label}{ext}"
                abs_path = os.path.join(media_path, unique_name)
                rel_path = f"scans/{unique_name}"

                with open(abs_path, 'wb+') as dest:
                    for chunk in img_file.chunks():
                        dest.write(chunk)

                saved_paths.append(abs_path)
                relative_paths.append(rel_path)

            # ── Step 1: OCR extraction across all uploaded images ────────────
            extracted_data = process_images(saved_paths)

            # ── Step 2: Model-based Real / Fake prediction ───────────────────
            pred = predictor.predict(extracted_data)
            model_label      = pred["label"]        # "Real" or "Fake"
            model_confidence = pred["confidence"]   # float 0-1

            # ── Step 3: Call Gemini AI for Expert Analysis ───────────────────
            ai_verdict = model_label
            ai_reason = "Analysis based on OCR and prediction models."
            
            try:
                import google.generativeai as genai
                # Configure if not already configured in this request
                genai.configure(api_key=settings.GEMINI_API_KEY)
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction="You are Vera, an expert cosmetic product authenticator. You are given data extracted via OCR and a ML prediction. Analyze it and provide a sophisticated expert verdict and one sentence reasoning. Also provide a brief cosmetic tip related to the product type if found."
                )
                
                # Context for Gemini
                prompt = f"""
                DATA EXTRACTED BY OCR:
                - Brand: {extracted_data.get('brand')}
                - Product: {extracted_data.get('product')}
                - Ingredients: {', '.join(extracted_data.get('ingredients', []))}
                - Barcode: {extracted_data.get('barcode')}
                - Batch: {extracted_data.get('batch')}
                - Raw Text Snippet: {extracted_data.get('raw_text', '')[:500]}
                
                ML MODEL PREDICTION:
                - Verdict: {model_label}
                - Confidence: {model_confidence*100:.1f}%
                
                Please return a JSON object with:
                "ai_verdict": "REAL" or "FAKE",
                "ai_reason": "One sentence expert analysis",
                "ai_tip": "A quick beauty tip related to these ingredients or product type"
                """
                
                response = model.generate_content(prompt)
                import json
                try:
                    # Clean markdown if Gemini adds it
                    resp_text = response.text.replace('```json', '').replace('```', '').strip()
                    ai_data = json.loads(resp_text)
                    ai_verdict = ai_data.get("ai_verdict", model_label)
                    ai_reason = ai_data.get("ai_reason", ai_reason)
                    ai_tip = ai_data.get("ai_tip", "")
                except Exception:
                    ai_reason = response.text[:200]
                    ai_tip = ""
            except Exception as e:
                # Fallback to model result if Gemini fails
                ai_reason = f"Gemini analysis unavailable: {str(e)}"
                ai_tip = ""

            # ── Step 4: Save to MongoDB ──────────────────────────────────────
            scan_record = ScanResult(
                image_path=relative_paths[0],
                image_paths=relative_paths,
                prediction_label=ai_verdict or model_label, # Use AI's verdict if available
                confidence_score=model_confidence,
                brand=extracted_data.get("brand"),
                product=extracted_data.get("product"),
                ingredients=extracted_data.get("ingredients", []),
                barcode=extracted_data.get("barcode"),
                batch=extracted_data.get("batch"),
                raw_text=extracted_data.get("raw_text")
            )
            scan_record.save()

            return Response({
                "message": "Scan record saved successfully.",
                "id": str(scan_record.id),
                # ── Model prediction ──
                "model_prediction":  model_label,
                "model_confidence":  model_confidence,
                "prediction_source": pred.get("source", "model"),
                # ── AI Analysis ──
                "ai_verdict": ai_verdict,
                "ai_reason": ai_reason,
                "ai_tip": ai_tip,
                # ── OCR data ──
                "brand":       extracted_data.get("brand"),
                "product":     extracted_data.get("product"),
                "ingredients": extracted_data.get("ingredients", []),
                "barcode":     extracted_data.get("barcode"),
                "batch":       extracted_data.get("batch"),
                # ── Meta ──
                "image_path":      relative_paths[0],
                "image_paths":     relative_paths,
                "images_received": len(image_files),
                "timestamp":       scan_record.timestamp,
            }, status=status.HTTP_201_CREATED)

        except ValueError:
            return Response(
                {"error": "Invalid format. confidence_score must be a float."},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def get(self, request):
        try:
            scans = ScanResult.objects.all().order_by('-timestamp')
            data = []
            for scan in scans:
                data.append({
                    "id":               str(scan.id),
                    "image_path":       scan.image_path,
                    "prediction_label": scan.prediction_label,
                    "confidence_score": scan.confidence_score,
                    "brand":            getattr(scan, 'brand', None),
                    "product":          getattr(scan, 'product', None),
                    "ingredients":      getattr(scan, 'ingredients', []),
                    "barcode":          getattr(scan, 'barcode', None),
                    "batch":            getattr(scan, 'batch', None),
                    "timestamp":        scan.timestamp.isoformat() if scan.timestamp else None
                })
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ChatAPIView(APIView):
    """
    Handles chatbot messages using Gemini AI.
    Integrates context from ScanResult if scan_id is provided.
    Stores chat history in MongoDB ChatLog.
    """
    def post(self, request):
        try:
            try:
                import google.generativeai as genai
            except ImportError:
                return Response({"error": "Gemini library not installed. Please run 'pip install google-generativeai'"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
            from .models import ChatLog, ScanResult
            
            user_message = request.data.get("message")
            scan_id = request.data.get("scan_id")

            if not user_message:
                return Response({"error": "Message is required."}, status=status.HTTP_400_BAD_REQUEST)

            # 1. Save User Message (even if scan_id is invalid, we save it as a string)
            user_log = ChatLog(role="user", content=user_message, scan_id=str(scan_id) if scan_id else None)
            user_log.save()

            # 2. Build Context from ScanResult
            context = ""
            if scan_id and len(str(scan_id)) == 24: # Basic check for ObjectId hex string
                try:
                    from bson import ObjectId
                    from bson.errors import InvalidId
                    try:
                        scan = ScanResult.objects.get(id=ObjectId(scan_id))
                        context = f"Current Product Scan Details:\n"
                        context += f"- Brand: {scan.brand or 'Unknown'}\n"
                        context += f"- Product: {scan.product or 'Unknown'}\n"
                        context += f"- Ingredients: {', '.join(scan.ingredients) if scan.ingredients else 'Not detected'}\n"
                        context += f"- Prediction: {scan.prediction_label} ({scan.confidence_score*100:.1f}% confidence)\n"
                        context += f"- Barcode: {scan.barcode or 'N/A'}\n"
                        context += f"- Extracted Text: {scan.raw_text[:500] if scan.raw_text else 'None'}\n"
                    except (ScanResult.DoesNotExist, InvalidId):
                        pass
                except ImportError:
                    # bson/pymongo missing
                    pass

            # 3. Initialize Gemini
            if not getattr(settings, 'GEMINI_API_KEY', None):
                 return Response({"error": "GEMINI_API_KEY not found in settings."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                system_instruction="You are Vera, an elegant and intelligent AI beauty companion for ScanSure. Help users verify product authenticity, understand ingredients, and get skincare advice. Be warm, sophisticated, and concise (under 60 words). Use the provided product context to answer questions specifically about the scanned product."
            )

            prompt = user_message
            if context:
                prompt = f"CONTEXT:\n{context}\n\nUSER QUESTION: {user_message}"

            # 4. Generate Response
            response = model.generate_content(prompt)
            # Handle potential empty response
            vera_reply = response.text if response and hasattr(response, 'text') else "I couldn't generate a response. Please try again."

            # 5. Save Vera Message
            vera_log = ChatLog(role="vera", content=vera_reply, scan_id=str(scan_id) if scan_id else None)
            vera_log.save()

            return Response({
                "reply": vera_reply,
                "role": "vera",
                "timestamp": vera_log.timestamp
            }, status=status.HTTP_200_OK)

        except Exception as e:
            import traceback
            print(traceback.format_exc()) # Log to console for user to see
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request):
        """Fetch chat history for a specific scan."""
        try:
            from .models import ChatLog
            scan_id = request.query_params.get("scan_id")
            
            if scan_id:
                logs = ChatLog.objects.filter(scan_id=scan_id).order_by('timestamp')
            else:
                # Fallback to recent general logs if no scan_id
                logs = ChatLog.objects.filter(scan_id=None).order_by('-timestamp')[:20][::-1]

            data = []
            for log in logs:
                data.append({
                    "role": log.role,
                    "content": log.content,
                    "timestamp": log.timestamp.isoformat()
                })
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

