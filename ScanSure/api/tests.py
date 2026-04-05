from django.test import TestCase
def test_api(request):
    return JsonResponse({"message": "API is working 🚀"})

# Create your tests here.
