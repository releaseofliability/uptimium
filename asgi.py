from app import app as application
from asgiref.wsgi import WsgiToAsgi

app = WsgiToAsgi(application)
