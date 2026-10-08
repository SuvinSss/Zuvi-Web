import json
from pathlib import Path
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.templatetags.static import static

@require_GET
def terms(request):
    return render(request, 'public/terms.html')

@require_GET
def manifest(request):
    store = request.GET.get('portal') == 'store'
    response=JsonResponse({'id':'/store/' if store else '/', 'name':'ZuuVi Store' if store else 'ZuuVi — The Boy Next Door', 'short_name':'ZuuVi Store' if store else 'ZuuVi', 'start_url':reverse('stores:store_portal_dashboard') if store else '/', 'scope':'/', 'display':'standalone', 'background_color':'#fafbf8', 'theme_color':'#226143', 'icons':[{'src':static(f'pwa/icon-{size}.png'),'sizes':f'{size}x{size}','type':'image/png','purpose':'any'} for size in [192,512]]})
    response['Content-Type']='application/manifest+json'
    return response

@require_GET
def service_worker(request):
    script=(Path(__file__).resolve().parent.parent/'static/pwa/service-worker.js').read_text()
    return HttpResponse(script,content_type='application/javascript',headers={'Cache-Control':'no-cache','Service-Worker-Allowed':'/'})
