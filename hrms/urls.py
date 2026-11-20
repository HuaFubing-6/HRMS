"""项目主路由。"""
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("app01.urls")),  # 业务路由全部收敛到 app01
]

# 开发环境下提供 media（头像）访问
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
