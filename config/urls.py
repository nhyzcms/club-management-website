"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import TemplateView
from django.views.static import serve

from common.views import SitePolicyView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('site-policy/', SitePolicyView.as_view(), name='site-policy'),
    path('auth/', include('accounts.urls')),
    path('tasks/', include('tasks.urls')),
    path('messaging/', include('messaging.urls')),
    path('activities/', include('activities.urls')),
    path('exam_board/', include('exam_board.urls')),
    path('news/', include('news.urls')),
    path('reviews/', include('reviews.urls')),
    path('about/', include('about.urls')),
    path('panorama/', include('panorama.urls')),
    path('announcements/', include('announcements.urls')),
    path('tutorials/', include('tutorials.urls')),
    path('recruitment/', include('recruitment.urls')),
    path('attachments/', include('attachments.urls')),
    path('uploads/', include('attachments.tus_urls')),
    re_path(r'^file/(?P<path>.*)$', serve, {'document_root': os.path.join(settings.BASE_DIR, 'media', 'file')}),
    
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    re_path(r'^(?!file/|static/|admin/|auth/|tasks/|media/|messaging/|activities/|news/|reviews/|site-policy/|exam_board/|tutorials/|recruitment/|attachments/|uploads/|about/|panorama/).*$', TemplateView.as_view(template_name='index.html'), name='index'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
 
