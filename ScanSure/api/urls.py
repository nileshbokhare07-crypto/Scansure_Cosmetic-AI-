from django.urls import path
from .views import ScanAPIView, ChatAPIView
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET'])
def test_api(request):
    return Response({"message": "API is working!"})

urlpatterns = [
    path('', test_api, name='test_api'),
    path('scan/', ScanAPIView.as_view(), name='scan-api'),
    path('chat/', ChatAPIView.as_view(), name='chat-api'),
]
