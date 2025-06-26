# bracesinfo/settings/prod.py

from .base import *
import os

# 安全性設定
DEBUG = False

# 從環境變數讀取 SECRET_KEY
# 這是您需要在 app.yaml 中設定的變數
SECRET_KEY = os.environ.get('SECRET_KEY')

# ALLOWED_HOSTS
# 在 App Engine 上，GCP 會處理好域名，設定 '*' 即可
# 或是更安全地設定為您的 appspot.com 域名和自訂域名
ALLOWED_HOSTS = ['*'] 

# 資料庫設定 (從 Cloud SQL 環境變數讀取)
# 這些變數同樣需要在 app.yaml 中設定
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': os.environ.get('DB_HOST'),       # e.g., /cloudsql/your-project-id:region:instance-name
        'USER': os.environ.get('DB_USER'),       # e.g., postgres
        'PASSWORD': os.environ.get('DB_PASS'),
        'NAME': os.environ.get('DB_NAME'),       # e.g., wagtail_db
    }
}

# 靜態檔案與媒體檔案 (設定到 Google Cloud Storage)
# GS_BUCKET_NAME 同樣需要在 app.yaml 中設定
GS_BUCKET_NAME = os.environ.get('GS_BUCKET_NAME')
STATICFILES_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'
DEFAULT_FILE_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'

STATIC_URL = f'https://storage.googleapis.com/{GS_BUCKET_NAME}/static/'
MEDIA_URL = f'https://storage.googleapis.com/{GS_BUCKET_NAME}/media/'


try:
    from .local import *
except ImportError:
    pass